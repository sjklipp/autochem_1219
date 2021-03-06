""" construct transition state z-matrices
"""
import functools
import numpy
from qcelemental import constants as qcc
import automol.formula
import automol.graph
import automol.graph.trans
import automol.convert.zmatrix
import automol.zmatrix
from automol.graph._graph import atom_neighbor_keys as _atom_neighbor_keys

ANG2BOHR = qcc.conversion_factor('angstrom', 'bohr')

def min_hyd_mig_dist(rct_zmas, prd_zmas):
    """ determines distance coordinate to minimize for hydrogen migration reaction
    """
    prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
    prd_gra = functools.reduce(automol.graph.union, prd_gras)
    if len(rct_zmas) == 1:
        rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
        rct_gra = functools.reduce(automol.graph.union, rct_gras)
        tras = automol.graph.trans.hydrogen_atom_migration(rct_gra, prd_gra)
        if tras is None:
            tras = automol.graph.trans.proton_migration(rct_gra, prd_gra)
        # If reaction found, then proceed
        if tras:
            min_frm_bnd_key = None
            min_dist = 10
            for tra in tras:
                frm_bnd_key, = automol.graph.trans.formed_bond_keys(tra)
                geo = automol.zmatrix.geometry(rct_zmas[0])
                dist = automol.geom.distance(geo, *list(frm_bnd_key))
                if dist < min_dist:
                    min_dist = dist
                    min_frm_bnd_key = frm_bnd_key
                if min_frm_bnd_key:
                    return min_frm_bnd_key
            #return min_frm_bnd_key 


def hydrogen_migration(rct_zmas, prd_zmas):
    """ z-matrix for a hydrogen migration reaction
    """
    ret = None, None, None, None, None

    # set products which will be unchanged to ts algorithm
    prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
    prd_gra = functools.reduce(automol.graph.union, prd_gras)
    count = 1
    while True:
        rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
        rct_gra = functools.reduce(automol.graph.union, rct_gras)

        # try an atom migration then try a proton migration
        tras = automol.graph.trans.hydrogen_atom_migration(rct_gra, prd_gra)
        if tras is None:
            tras = automol.graph.trans.proton_migration(rct_gra, prd_gra)

        # If reaction found, then proceed
        if tras:
            # Get the bond formation keys and the reactant zmatrix
            min_dist = 100.
            frm_bnd_key = None
            brk_bnd_key = None
            for tra_i in tras:
                # Get the bond formation and breaking keys
                bnd_key, = automol.graph.trans.formed_bond_keys(tra_i)
                geo = automol.zmatrix.geometry(rct_zmas[0])
                dist = automol.geom.distance(geo, *list(bnd_key))
                if dist < min_dist:
                    min_dist = dist
                    frm_bnd_key = bnd_key
                    brk_bnd_key = automol.graph.trans.broken_bond_keys(tra_i)
                    tra = tra_i
                init_zma, = rct_zmas

            # figure out which idx in frm_bnd_keys corresponds to the hydrogen
            symbols = automol.vmatrix.symbols(automol.zmatrix.var_(init_zma))
            dist_coo_key = tuple(reversed(sorted(frm_bnd_key)))
            for idx in dist_coo_key:
                if symbols[idx] == 'H':
                    h_idx = idx
                else:
                    a1_idx = idx

            # determine if the zmatrix needs to be rebuilt by x2z
            # determines if the hydrogen atom is used to define other atoms
            init_keys = automol.zmatrix.key_matrix(init_zma)
            rebuild = False
            for i, _ in enumerate(init_keys):
                if i > h_idx and any(idx == h_idx for idx in init_keys[i]):
                    rebuild = True
                    break

            # rebuild zmat and go through while loop again if needed
            # shifts order of cartesian coords and rerun x2z to get a new zmat
            # else go to next stage
            if rebuild:
                reord_zma = _reorder_zmatrix_for_migration(
                    init_zma, a1_idx, h_idx)
                rct_zmas = [reord_zma]
                count += 1
                if count == 3:
                    break
            else:
                rct_zma = init_zma
                break
        else:
            return None

    # if migrating H atom is not the final zmat entry, shift it to the end
    # if h_idx != automol.zmatrix.count(rct_zma) - 1:
    #    rct_zma = automol.zmatrix.shift_row_to_end(rct_zma, h_idx)

    # determine the backbone atoms to redefine the z-matrix entry
    _, gras = _shifted_standard_forms_with_gaphs([rct_zma], remove_stereo=True)
    gra = functools.reduce(automol.graph.union, gras)
    xgr1, = automol.graph.connected_components(gra)
    chains_dct = automol.graph.atom_longest_chains(xgr1)
    a2_idx = chains_dct[a1_idx][1]
    a3_idx = chains_dct[a1_idx][2]
    if a3_idx == h_idx:
        a1_neighbors = _atom_neighbor_keys(xgr1)[a1_idx]
        for idx in a1_neighbors:
            if idx not in (h_idx, a2_idx):
                a3_idx = idx
    if a2_idx > h_idx or a3_idx > h_idx:
        atm_ngb_keys_dct = automol.graph.atom_neighbor_keys(gra)
        ngbs = atm_ngb_keys_dct[a1_idx]
        for idx in ngbs:
            if idx not in [h_idx]:
                new_ngbs = atm_ngb_keys_dct[idx]
                for new_idx in new_ngbs:
                    if new_idx not in [a1_idx, h_idx]:
                        a2_idx = idx
                        a3_idx = new_idx
                        break
    # determine the new coordinates
    rct_geo = automol.zmatrix.geometry(rct_zma)
    distance = automol.geom.distance(
        rct_geo, h_idx, a1_idx)
    angle = automol.geom.central_angle(
        rct_geo, h_idx, a1_idx, a2_idx)
    dihedral = automol.geom.dihedral_angle(
        rct_geo, h_idx, a1_idx, a2_idx, a3_idx)

    dihed_is_180 = numpy.isclose(
        abs(dihedral), (numpy.pi), rtol=(5.0 * numpy.pi / 180.))
    dihed_is_0 = numpy.isclose(
        dihedral, (0.0), rtol=(5.0 * numpy.pi / 180.))
    dihed_is_360 = numpy.isclose(
        abs(dihedral), (2*numpy.pi), rtol=(5.0 * numpy.pi / 180.))

    if dihed_is_180 or dihed_is_0 or dihed_is_360:
        dihedral -= (15.0 * numpy.pi / 180.)

    # Reset the keys for the migrating H atom
    new_idxs = (a1_idx, a2_idx, a3_idx)
    key_dct = {h_idx: new_idxs}
    ts_zma = automol.zmatrix.set_keys(rct_zma, key_dct)
    # Reset the values in the value dict
    h_names = automol.zmatrix.name_matrix(ts_zma)[h_idx]
    ts_zma = automol.zmatrix.set_values(
        ts_zma, {h_names[0]: distance,
                 h_names[1]: angle,
                 h_names[2]: dihedral}
    )

    # standardize the ts zmat and get tors and dist coords
    coo_dct = automol.zmatrix.coordinates(ts_zma)
    dist_name = next(coo_name for coo_name, coo_keys in coo_dct.items()
                     if dist_coo_key in coo_keys)
    ts_name_dct = automol.zmatrix.standard_names(ts_zma)
    dist_name = ts_name_dct[dist_name]
    ts_zma = automol.zmatrix.standard_form(ts_zma)

    # get full set of potential torsional coordinates
    pot_tors_names = automol.zmatrix.torsion_coordinate_names(ts_zma)

    # remove the torsional coordinates that would break reaction coordinate
    gra = automol.zmatrix.graph(ts_zma, remove_stereo=True)
    coo_dct = automol.zmatrix.coordinates(ts_zma)
    tors_names = []
    for tors_name in pot_tors_names:
        axis = coo_dct[tors_name][0][1:3]
        grp1 = [axis[1]] + (
            list(automol.graph.branch_atom_keys(gra, axis[0], axis) -
                 set(axis)))
        grp2 = [axis[0]] + (
            list(automol.graph.branch_atom_keys(gra, axis[1], axis) -
                 set(axis)))
        if not ((h_idx in grp1 and a1_idx in grp2) or
                (h_idx in grp2 and a1_idx in grp1)):
            tors_names.append(tors_name)

    ret = ts_zma, dist_name, frm_bnd_key, brk_bnd_key, tors_names

    return ret


def min_unimolecular_elimination_dist(rct_zmas, prd_zmas):
    """ determines distance coordinate to minimize for a concerted unimolecular elimination reaction
    """
    prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
    prds_gra = functools.reduce(automol.graph.union, prd_gras)
    if len(rct_zmas) == 1:
        rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
        rcts_gra = functools.reduce(automol.graph.union, rct_gras)

        print('rct_zmas in elim:', rct_zmas)
        print('prd_zmas in elim:', prd_zmas)

        tras = automol.graph.trans.elimination(rcts_gra, prds_gra)
        print('tras test:', tras)
        #frm_bnd_key, = automol.graph.trans.formed_bond_keys(tras)
        #return frm_bnd_key
        if tras:
            if len(tras[0]) == 1:
                tras = [tras]
            min_frm_bnd_key = None
            min_dist = 10
            for tra in tras:
                print('tra test:', tra)
                #frm_bnd_key = tra
                frm_bnd_key, = automol.graph.trans.formed_bond_keys(tra)
                geo = automol.zmatrix.geometry(rct_zmas[0])
                dist = automol.geom.distance(geo, *list(frm_bnd_key))
                if dist < min_dist:
                    min_dist = dist
                    min_frm_bnd_key = frm_bnd_key
                #if min_frm_bnd_key:
                    #return min_frm_bnd_key
            return min_frm_bnd_key


def concerted_unimolecular_elimination(rct_zmas, prd_zmas):
    """ z-matrix for a concerted unimolecular elimination reaction
    """
    ret = None, None, None, None, None
    prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
    prds_gra = functools.reduce(automol.graph.union, prd_gras)
    if len(rct_zmas) == 1:
        count = 1
        while True:
            rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
            rcts_gra = functools.reduce(automol.graph.union, rct_gras)
            init_zma, = rct_zmas

            tras = automol.graph.trans.elimination(rcts_gra, prds_gra)
            if tras is not None:
                if len(tras[0]) == 1:
                    tras = [tras]
                min_dist = 100.
                frm_bnd_key = None
                for tra_i in tras:
                    # Get the bond formation and breaking keys
                    bnd_key, = automol.graph.trans.formed_bond_keys(tra_i)
                    geo = automol.zmatrix.geometry(rct_zmas[0])
                    dist = automol.geom.distance(geo, *list(bnd_key))
                    if dist < min_dist:
                        min_dist = dist
                        frm_bnd_key = bnd_key
                        tra = tra_i
                brk_bnd_key1, brk_bnd_key2 = automol.graph.trans.broken_bond_keys(
                    tra)
                init_zma, = rct_zmas

                # Get index for migrating atom (or bond-form atom in group)
                for bnd_key in (brk_bnd_key1, brk_bnd_key2):
                    if bnd_key & frm_bnd_key:
                        mig_key = next(iter(bnd_key & frm_bnd_key))
                for key in frm_bnd_key:
                    if key != mig_key:
                        a1_idx = key

                # Get chain for redefining the rc1_atm1_key z-matrix entries
                _, gras = _shifted_standard_forms_with_gaphs([init_zma], remove_stereo=True)
                gra = functools.reduce(automol.graph.union, gras)
                xgr1, = automol.graph.connected_components(gra)
                atm1_neighbors = _atom_neighbor_keys(xgr1)[a1_idx]
                for idx in atm1_neighbors:
                    if idx != mig_key and len(_atom_neighbor_keys(xgr1)[idx]) > 1:
                        a2_idx = idx
                atm2_neighbors = _atom_neighbor_keys(xgr1)[a2_idx]
                for idx in atm2_neighbors:
                    if idx != mig_key and idx != a1_idx:
                        a3_idx = idx

                mig_redef_keys = (a1_idx, a2_idx, a3_idx)

                # determine if the zmatrix needs to be rebuilt by x2z
                # determines if the hydrogen atom is used to define other atoms
                rebuild = False
                if any(idx > mig_key for idx in mig_redef_keys):
                    rebuild = True

                # rebuild zmat and go through while loop again if needed
                # shifts order of cartesian coords and rerun x2z to get a new zmat
                # else go to next stage
                if rebuild:
                    reord_zma = _reorder_zmatrix_for_migration(
                        init_zma, a1_idx, mig_key)
                    rct_zmas = [reord_zma]
                    count += 1
                    if count == 3:
                        break
                else:
                    rct_zma = init_zma
                    break
            else:
                return None, None, None, None, None

        # determine the new coordinates
        rct_geo = automol.zmatrix.geometry(rct_zma)
        distance = automol.geom.distance(
            rct_geo, mig_key, a1_idx)
        angle = automol.geom.central_angle(
            rct_geo, mig_key, a1_idx, a2_idx)
        dihedral = automol.geom.dihedral_angle(
            rct_geo, mig_key, a1_idx, a2_idx, a3_idx)
        # Reset the keys for the migrating H atom
        new_idxs = (a1_idx, a2_idx, a3_idx)
        key_dct = {mig_key: new_idxs}
        ts_zma = automol.zmatrix.set_keys(rct_zma, key_dct)

        # Reset the values in the value dict
        mig_names = automol.zmatrix.name_matrix(ts_zma)[mig_key]
        ts_zma = automol.zmatrix.set_values(
            ts_zma, {mig_names[0]: distance,
                     mig_names[1]: angle,
                     mig_names[2]: dihedral}
        )

        # standardize the ts zmat and get tors and dist coords
        coo_dct = automol.zmatrix.coordinates(ts_zma)
        dist_coo_key = tuple(reversed(sorted(frm_bnd_key)))
        dist_name = next(coo_name for coo_name, coo_keys in coo_dct.items()
                         if dist_coo_key in coo_keys)
        ts_name_dct = automol.zmatrix.standard_names(ts_zma)
        dist_name = ts_name_dct[dist_name]
        ts_zma = automol.zmatrix.standard_form(ts_zma)

        # Get the name of the coordinate of the other bond that is breaking
        print('elim name check')
        print(brk_bnd_key1)
        print(brk_bnd_key2)
        brk_dist_name = None
        for brk_key in (brk_bnd_key1, brk_bnd_key2):
            if not brk_key.intersection(frm_bnd_key):
                brk_dist_name = automol.zmatrix.bond_key_from_idxs(ts_zma, brk_key)

        # Add second attempt to get brk_dist_name
        if brk_dist_name is None:
            brk_dist_names = [
                automol.zmatrix.bond_key_from_idxs(ts_zma, brk_bnd_key1),
                automol.zmatrix.bond_key_from_idxs(ts_zma, brk_bnd_key2)
            ]
            # Grab the name that is not None
            for name in brk_dist_names:
                if name is not None:
                    brk_dist_name = name
        print(dist_name)
        print(brk_dist_name)
        print(automol.zmatrix.string(ts_zma))
        # import sys
        # sys.exit()


        # get full set of potential torsional coordinates
        pot_tors_names = automol.zmatrix.torsion_coordinate_names(rct_zma)

        # remove the torsional coordinates that would break reaction coordinate
        gra = automol.zmatrix.graph(ts_zma, remove_stereo=True)
        coo_dct = automol.zmatrix.coordinates(ts_zma)
        tors_names = []
        for tors_name in pot_tors_names:
            axis = coo_dct[tors_name][0][1:3]
            grp1 = [axis[1]] + (
                list(automol.graph.branch_atom_keys(gra, axis[0], axis) -
                     set(axis)))
            grp2 = [axis[0]] + (
                list(automol.graph.branch_atom_keys(gra, axis[1], axis) -
                     set(axis)))
            if not ((mig_key in grp1 and a1_idx in grp2) or
                    (mig_key in grp2 and a1_idx in grp1)):
                tors_names.append(tors_name)

        ret = ts_zma, dist_name, brk_dist_name, frm_bnd_key, tors_names

        return ret


def concerted_unimolecular_elimination2(rct_zmas, prd_zmas):
    """ z-matrix for a concerted unimolecular elimination reaction
    """
    ret = None, None, None, None
    prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
    prds_gra = functools.reduce(automol.graph.union, prd_gras)
    if len(rct_zmas) == 1:
        count = 1
        while True:
            rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
            rcts_gra = functools.reduce(automol.graph.union, rct_gras)
            init_zma, = rct_zmas

            tras = automol.graph.trans.elimination(rcts_gra, prds_gra)
            if tras is not None:
                min_dist = 100.
                frm_bnd_key = None
                for tra_i in tras:
                    # Get the bond formation and breaking keys
                    bnd_key, = automol.graph.trans.formed_bond_keys(tra_i)
                    geo = automol.zmatrix.geometry(rct_zmas[0])
                    dist = automol.geom.distance(geo, *list(bnd_key))
                    if dist < min_dist:
                        min_dist = dist
                        frm_bnd_key = bnd_key
                        tra = tra_i
                brk_bnd_key1, brk_bnd_key2 = automol.graph.trans.broken_bond_keys(
                                                tra)
                init_zma, = rct_zmas

                # Get index for migrating atom (or bond-form atom in group)
                for bnd_key in (brk_bnd_key1, brk_bnd_key2):
                    if bnd_key & frm_bnd_key:
                        key_iter = iter(bnd_key & frm_bnd_key)
                        mig_key = next(key_iter)
                        a1_idx = next(key_iter)

                # Get chain for redefining the rc1_atm1_key z-matrix entries
                _, gras = _shifted_standard_forms_with_gaphs([init_zma], remove_stereo=True)
                gra = functools.reduce(automol.graph.union, gras)
                xgr1, = automol.graph.connected_components(gra)
                atm1_neighbors = _atom_neighbor_keys(xgr1)[a1_idx]
                for idx in atm1_neighbors:
                    if idx != mig_key and len(_atom_neighbor_keys(xgr1)[idx]) > 1:
                        a2_idx = idx
                atm2_neighbors = _atom_neighbor_keys(xgr1)[a2_idx]
                for idx in atm2_neighbors:
                    if idx != mig_key:
                        a3_idx = idx

                mig_redef_keys = (a1_idx, a2_idx, a3_idx)

                # determine if the zmatrix needs to be rebuilt by x2z
                # determines if the hydrogen atom is used to define other atoms
                rebuild = False
                if any(idx > mig_key for idx in mig_redef_keys):
                    rebuild = True

                # rebuild zmat and go through while loop again if needed
                # shifts order of cartesian coords and rerun x2z to get a new zmat
                # else go to next stage
                if rebuild:
                    reord_zma = _reorder_zmatrix_for_migration(
                        init_zma, a1_idx, mig_key)
                    rct_zmas = [reord_zma]
                    count += 1
                    if count == 3:
                        break
                else:
                    rct_zma = init_zma
                    break
            else:
                return None, None, None, None
        
        # Get the name of the coordinates for the bonds breaking
        brk_names = []
        for brk_key in (brk_bnd_key1, brk_bnd_key2):
            brk_names.append(
                automol.zmatrix.bond_key_from_idxs(ts_zma, brk_key))

        # increase the length of the bond breaking coordinates
        for name in brk_names:
            val = automol.zmatrix.values(ts_zma)[name]
            ts_zma = automol.zmatrix.set_values(
                ts_zma, {name: val + (0.4 * ANG2BOHR)})

        # determine the new coordinates
        rct_geo = automol.zmatrix.geometry(rct_zma)
        distance = automol.geom.distance(
            rct_geo, mig_key, a1_idx)
        angle = automol.geom.central_angle(
            rct_geo, mig_key, a1_idx, a2_idx)
        dihedral = automol.geom.dihedral_angle(
            rct_geo, mig_key, a1_idx, a2_idx, a3_idx)
        # Reset the keys for the migrating H atom
        new_idxs = (a1_idx, a2_idx, a3_idx)
        key_dct = {mig_key: new_idxs}
        ts_zma = automol.zmatrix.set_keys(rct_zma, key_dct)

        # Reset the values in the value dict
        mig_names = automol.zmatrix.name_matrix(ts_zma)[mig_key]
        ts_zma = automol.zmatrix.set_values(
            ts_zma, {mig_names[0]: distance,
                     mig_names[1]: angle,
                     mig_names[2]: dihedral}
        )

        # standardize the ts zmat and get tors and dist coords
        coo_dct = automol.zmatrix.coordinates(ts_zma)
        dist_coo_key = tuple(reversed(sorted(frm_bnd_key)))
        dist_name = next(coo_name for coo_name, coo_keys in coo_dct.items()
                         if dist_coo_key in coo_keys)
        ts_name_dct = automol.zmatrix.standard_names(ts_zma)
        dist_name = ts_name_dct[dist_name]
        ts_zma = automol.zmatrix.standard_form(ts_zma)

        # Get the name of the coordinate of the other bond that is breaking
        for brk_key in (brk_bnd_key1, brk_bnd_key2):
            if not brk_key.intersection(frm_bnd_key):
                brk_dist_name = automol.zmatrix.bond_key_from_idxs(ts_zma, brk_key)

        # get full set of potential torsional coordinates
        pot_tors_names = automol.zmatrix.torsion_coordinate_names(rct_zma)

        # remove the torsional coordinates that would break reaction coordinate
        gra = automol.zmatrix.graph(ts_zma, remove_stereo=True)
        coo_dct = automol.zmatrix.coordinates(ts_zma)
        tors_names = []
        for tors_name in pot_tors_names:
            axis = coo_dct[tors_name][0][1:3]
            grp1 = [axis[1]] + (
                list(automol.graph.branch_atom_keys(gra, axis[0], axis) -
                     set(axis)))
            grp2 = [axis[0]] + (
                list(automol.graph.branch_atom_keys(gra, axis[1], axis) -
                     set(axis)))
            if not ((mig_key in grp1 and a1_idx in grp2) or
                    (mig_key in grp2 and a1_idx in grp1)):
                tors_names.append(tors_name)

        ret = ts_zma, dist_name, brk_dist_name, frm_bnd_key, tors_names

        return ret


def _reorder_zmatrix_for_migration(zma, a_idx, h_idx):
    """ performs z-matrix reordering operations required to
        build proper z-matrices for hydrogen migrations
    """

    # initialize zmat components neededlater
    symbols = automol.zmatrix.symbols(zma)

    # Get the longest chain for all the atoms
    _, gras = _shifted_standard_forms_with_gaphs([zma], remove_stereo=True)
    gra = functools.reduce(automol.graph.union, gras)
    xgr1, = automol.graph.connected_components(gra)
    chains_dct = automol.graph.atom_longest_chains(xgr1)

    # find the longest heavy-atom chain for the forming atom
    form_chain = chains_dct[a_idx]

    # get the indices used for reordering
    # get the longest chain from the bond forming atom (not including H)
    order_idxs = [idx for idx in form_chain
                  if symbols[idx] != 'H' and idx != h_idx]

    # add all the heavy-atoms not in the chain
    for i, atom in enumerate(symbols):
        if i not in order_idxs and atom != 'H':
            order_idxs.append(i)

    # add all the hydrogens
    for i, atom in enumerate(symbols):
        if i != h_idx and atom == 'H':
            order_idxs.append(i)

    # add the migrating atoms
    order_idxs.append(h_idx)

    # get the geometry and redorder it according to the order_idxs list
    geo = [list(x) for x in automol.zmatrix.geometry(zma)]
    geo2 = tuple(tuple(geo[idx]) for idx in order_idxs)

    # convert to a z-matrix
    zma_ret = automol.geom.zmatrix(geo2)

    return zma_ret


def insertion(rct_zmas, prd_zmas):
    """ z-matrix for an insertion reaction
    """
    ret = None
    dist_name = 'rts'
    dist_val = 3.
    rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
    prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
    rcts_gra = functools.reduce(automol.graph.union, rct_gras)
    prds_gra = functools.reduce(automol.graph.union, prd_gras)
    tra, idxs = automol.graph.trans.insertion(rcts_gra, prds_gra)
    if tra is not None:
        frm_bnd_key, _ = automol.graph.trans.formed_bond_keys(tra)
        # brk_bnd_key, = automol.graph.trans.broken_bond_keys(tra)

        # get the atom on react 1 that is being attacked (bond is forming)
        rct1_atm1_key = list(frm_bnd_key)[0]

        # figure out atoms in the chain to define the dummy atom
        _, rct2_gra = map(rct_gras.__getitem__, idxs)
        rct1_zma, rct2_zma = map(rct_zmas.__getitem__, idxs)
        rct1_natms = automol.zmatrix.count(rct1_zma)
        rct2_natms = automol.zmatrix.count(rct2_zma)

        rct1_atm2_key, rct1_atm3_key, _ = _join_atom_keys(
            rct1_zma, rct1_atm1_key)

        x_zma = ((('X', (None, None, None), (None, None, None)),), {})

        x_join_val_dct = {
            'rx': 1. * qcc.conversion_factor('angstrom', 'bohr'),
            'ax': 90. * qcc.conversion_factor('degree', 'radian'),
            'dx': 180. * qcc.conversion_factor('degree', 'radian'),
        }

        x_join_keys = numpy.array(
            [[rct1_atm1_key, rct1_atm2_key, rct1_atm3_key]])
        x_join_names = numpy.array([['rx', 'ax', 'dx']],
                                   dtype=numpy.object_)
        x_join_names[numpy.equal(x_join_keys, None)] = None
        x_join_name_set = set(numpy.ravel(x_join_names)) - {None}
        x_join_val_dct = {name: x_join_val_dct[name]
                          for name in x_join_name_set}
        rct1_x_zma = automol.zmatrix.join(
            rct1_zma, x_zma, x_join_keys, x_join_names, x_join_val_dct)
        x_atm_key = rct1_natms

        join_val_dct = {
            dist_name: dist_val,
            'aabs1': 85. * qcc.conversion_factor('degree', 'radian'),
            'aabs2': 85. * qcc.conversion_factor('degree', 'radian'),
            'babs1': 170. * qcc.conversion_factor('degree', 'radian'),
            'babs2': 85. * qcc.conversion_factor('degree', 'radian'),
            'babs3': 85. * qcc.conversion_factor('degree', 'radian'),
        }

        join_keys = numpy.array(
            [[rct1_atm1_key, x_atm_key, rct1_atm2_key],
             [None, rct1_atm1_key, x_atm_key],
             [None, None, rct1_atm1_key]])[:rct2_natms]
        join_names = numpy.array(
            [[dist_name, 'aabs1', 'babs1'],
             [None, 'aabs2', 'babs2'],
             [None, None, 'babs3']])[:rct2_natms]
        join_names[numpy.equal(join_keys, None)] = None

        join_name_set = set(numpy.ravel(join_names)) - {None}
        join_val_dct = {name: join_val_dct[name] for name in join_name_set}

        ts_zma = automol.zmatrix.join(
            rct1_x_zma, rct2_zma, join_keys, join_names, join_val_dct)

        ts_name_dct = automol.zmatrix.standard_names(ts_zma)
        dist_name = ts_name_dct[dist_name]
        ts_zma = automol.zmatrix.standard_form(ts_zma)
        # CHECK IF THE INSERTION MESSES WITH THE TORSION ASSIGNMENTS
        rct1_tors_names = automol.zmatrix.torsion_coordinate_names(
            rct1_zma)
        rct2_tors_names = automol.zmatrix.torsion_coordinate_names(
            rct2_zma)
        tors_names = (
            tuple(map(ts_name_dct.__getitem__, rct1_tors_names)) +
            tuple(map(ts_name_dct.__getitem__, rct2_tors_names))
        )

        if 'babs2' in ts_name_dct:
            geo1 = automol.convert.zmatrix.geometry(rct1_zma)
            if not automol.geom.is_linear(geo1):
                tors_name = ts_name_dct['babs2']
                tors_names += (tors_name,)

        if 'babs3' in ts_name_dct and _include_babs3(frm_bnd_key, rct2_gra):
            tors_name = ts_name_dct['babs3']
            tors_names += (tors_name,)
        ret = ts_zma, dist_name, tors_names

    return ret


def substitution(rct_zmas, prd_zmas):
    """ z-matrix for a substitution reaction
    Presume that radical substitutions at a pi bond occur instead as
    a sequence of addition and elimination.
    Also, for now presume that we are only interested in radical molecule substitutions
    """
    ret = None

    # Set the name and value for the bond being formed
    dist_name = 'rts'
    dist_val = 3.

    # first determine if this is a radical molecule reaction and then if the radical is the first species
    # reorder to put it second
    rad_cnt = 0
    mol_cnt = 0
    print('rct_zmas in subs:', rct_zmas)
    for idx, rct_zma in enumerate(rct_zmas):
        rad_keys = automol.graph.resonance_dominant_radical_atom_keys(
            automol.geom.graph(automol.zmatrix.geometry(rct_zma)))
        ich = automol.geom.inchi(automol.zmatrix.geometry(rct_zma))
        is_co = (ich == 'InChI=1S/CO/c1-2')
        if rad_keys and not is_co:
            rad_idx = idx
            rad_cnt += 1
            print('rad')
        else:
            # mol_idx = idx
            mol_cnt += 1

    print('rad_cnt, mol_cnt:', rad_cnt, mol_cnt)
    if rad_cnt == 1 and mol_cnt == 1:
        if rad_idx == 0:
            rct2_zma, rct1_zma = rct_zmas
            rct_zmas = [rct1_zma, rct2_zma]
        # Confirm the reaction type and build the appropriate Z-Matrix

        rct2_gra = automol.zmatrix.graph(rct_zmas[1], remove_stereo=True)
        rad_atm_keys = automol.graph.resonance_dominant_radical_atom_keys(rct2_gra)
        if 0 not in rad_atm_keys:
            rct_zmas[1] = _reorder_zma_for_radicals(rct_zmas[1], min(rad_atm_keys))
            rct2_gra = automol.zmatrix.graph(rct_zmas[1], remove_stereo=True)
            rad_atm_keys = automol.graph.resonance_dominant_radical_atom_keys(rct2_gra)
            # following assert checks to ensure that the first atom in the second reactant is a radical
            # this is required for the remainder of the routine
            assert 0 in rad_atm_keys

        rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
        prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
        rcts_gra = functools.reduce(automol.graph.union, rct_gras)
        prds_gra = functools.reduce(automol.graph.union, prd_gras)

        tra, idxs = automol.graph.trans.substitution(rcts_gra, prds_gra)
        #print(tra)
    else:
        tra = None
    if tra is not None:
        frm_bnd_key, = automol.graph.trans.formed_bond_keys(tra)
        # brk_bnd_key, = automol.graph.trans.broken_bond_keys(tra)

        # get the atom on react 1 that is being attacked (bond is forming)
        rct1_atm1_key = list(frm_bnd_key)[0]

        rct_zmas, prd_zmas = map([rct_zmas, prd_zmas].__getitem__, idxs[0])
        rct1_zma, rct2_zma = map(rct_zmas.__getitem__, idxs[1])
        _, rct2_gra = map(rct_gras.__getitem__, idxs[1])
        rct1_natms = automol.zmatrix.count(rct1_zma)
        rct2_natms = automol.zmatrix.count(rct2_zma)

        # figure out atoms in the chain to define the dummy atom
        rct1_atm2_key, rct1_atm3_key, _ = _join_atom_keys(
            rct1_zma, rct1_atm1_key)

        # Join the reactant 1 ZMAT with the dummy atomx
        x_zma = ((('X', (None, None, None), (None, None, None)),), {})

        x_join_val_dct = {
            'rx': 1. * qcc.conversion_factor('angstrom', 'bohr'),
            'ax': 90. * qcc.conversion_factor('degree', 'radian'),
            'dx': 180. * qcc.conversion_factor('degree', 'radian'),
        }

        x_join_keys = numpy.array(
            [[rct1_atm1_key, rct1_atm2_key, rct1_atm3_key]])
        x_join_names = numpy.array([['rx', 'ax', 'dx']],
                                   dtype=numpy.object_)
        x_join_names[numpy.equal(x_join_keys, None)] = None
        x_join_name_set = set(numpy.ravel(x_join_names)) - {None}
        x_join_val_dct = {name: x_join_val_dct[name]
                          for name in x_join_name_set}

        rct1_x_zma = automol.zmatrix.join(
            rct1_zma, x_zma, x_join_keys, x_join_names, x_join_val_dct)

        # Join the React 2 ZMAT with the reac1_x ZMAT
        x_atm_key = rct1_natms

        join_val_dct = {
            dist_name: dist_val,
            'aabs1': 85. * qcc.conversion_factor('degree', 'radian'),
            'aabs2': 85. * qcc.conversion_factor('degree', 'radian'),
            'babs1': 170. * qcc.conversion_factor('degree', 'radian'),
            'babs2': 85. * qcc.conversion_factor('degree', 'radian'),
            'babs3': 85. * qcc.conversion_factor('degree', 'radian'),
        }

        join_keys = numpy.array(
            [[rct1_atm1_key, x_atm_key, rct1_atm2_key],
             [None, rct1_atm1_key, x_atm_key],
             [None, None, rct1_atm1_key]])[:rct2_natms]
        join_names = numpy.array(
            [[dist_name, 'aabs1', 'babs1'],
             [None, 'aabs2', 'babs2'],
             [None, None, 'babs3']])[:rct2_natms]
        join_names[numpy.equal(join_keys, None)] = None

        join_name_set = set(numpy.ravel(join_names)) - {None}
        join_val_dct = {name: join_val_dct[name] for name in join_name_set}

        ts_zma = automol.zmatrix.join(
            rct1_x_zma, rct2_zma, join_keys, join_names, join_val_dct)

        # Get the names of the coordinates of the breaking and forming bond
        ts_name_dct = automol.zmatrix.standard_names(ts_zma)
        form_dist_name = ts_name_dct[dist_name]
        #break_dist_name = automol.zmatrix.bond_key_from_idxs(ts_zma, brk_bnd_key)

        # Get the torsional coordinates of the transition state
        ts_zma = automol.zmatrix.standard_form(ts_zma)
        rct1_tors_names = automol.zmatrix.torsion_coordinate_names(
            rct1_zma)
        rct2_tors_names = automol.zmatrix.torsion_coordinate_names(
            rct2_zma)
        tors_names = (
            tuple(map(ts_name_dct.__getitem__, rct1_tors_names)) +
            tuple(map(ts_name_dct.__getitem__, rct2_tors_names))
        )

        if 'babs2' in ts_name_dct:
            geo1 = automol.convert.zmatrix.geometry(rct1_zma)
            if not automol.geom.is_linear(geo1):
                tors_name = ts_name_dct['babs2']
                tors_names += (tors_name,)

        if 'babs3' in ts_name_dct and _include_babs3(frm_bnd_key, rct2_gra):
            tors_name = ts_name_dct['babs3']
            tors_names += (tors_name,)

        # Set info to be returned
        ret = ts_zma, form_dist_name, tors_names

    return ret


def beta_scission(rct_zmas, prd_zmas):
    """ z-matrix for a beta-scission reaction
    """
    ret = None
    rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
    prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
    rcts_gra = functools.reduce(automol.graph.union, rct_gras)
    prds_gra = functools.reduce(automol.graph.union, prd_gras)
    tra = automol.graph.trans.beta_scission(rcts_gra, prds_gra)
    if tra is not None:
        brk_bnd_key, = automol.graph.trans.broken_bond_keys(tra)
        ts_zma, = rct_zmas
        coo_dct = automol.zmatrix.coordinates(ts_zma)
        dist_coo_key = tuple(reversed(sorted(brk_bnd_key)))
        dist_name = next(coo_name for coo_name, coo_keys in coo_dct.items()
                         if dist_coo_key in coo_keys)

        ts_name_dct = automol.zmatrix.standard_names(ts_zma)
        dist_name = ts_name_dct[dist_name]
        ts_zma = automol.zmatrix.standard_form(ts_zma)
        tors_names = automol.zmatrix.torsion_coordinate_names(ts_zma)

        ret = ts_zma, dist_name, tors_names

    return ret


def addition(rct_zmas, prd_zmas, rct_tors=[]):
    """ z-matrix for an addition reaction
    """
    ret = None
    dist_name = 'rts'
    dist_val = 3.


    count1 = automol.zmatrix.count(rct_zmas[0])
    if len(rct_zmas) == 2:
        count2 = automol.zmatrix.count(rct_zmas[1])
        print('rct_zmas:', rct_zmas[0], rct_zmas[1])
        if count1 == 1 or count1 < count2:
            rct2_zma, rct1_zma = rct_zmas
            rct_zmas = [rct1_zma, rct2_zma]
    rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
    prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
    rcts_gra = functools.reduce(automol.graph.union, rct_gras)
    prds_gra = functools.reduce(automol.graph.union, prd_gras)
    tra = automol.graph.trans.addition(rcts_gra, prds_gra)
    if tra is not None:
        rct1_zma, rct2_zma = rct_zmas
        rct1_gra, rct2_gra = rct_gras
        rct2_natms = automol.zmatrix.count(rct2_zma)

        frm_bnd_key, = automol.graph.trans.formed_bond_keys(tra)
        rct1_atm1_key, _ = sorted(frm_bnd_key)

        #Replace old routine with new one based on unsaturated atoms
        # Start of new routine
        rct1_unsat_keys = automol.graph.unsaturated_atom_keys(rct1_gra)
        # get neighbor keys for rct1_atm1_key
        neighbor_dct = automol.graph.atom_neighbor_keys(rct1_gra)
        atm1_nghbr_keys = neighbor_dct[rct1_atm1_key]
        # shift keys for unsaturated atoms and for atm1_nghbr keys to include dummy atoms

        # second atom key
        # choose rct1_atm2 as first unsaturated neighbor to rct1_atm1
        rct1_atm2_key = None
        for key in atm1_nghbr_keys:
            if key in rct1_unsat_keys:
                rct1_atm2_key = key
                break

        # if no unsaturated neighbor, choose any atm1_nghbr
        if rct1_atm2_key is None:
            for key in atm1_nghbr_keys:
                rct1_atm2_key = key
                break

        # third atom key
        # if atm1 has two neighbors choose third atom key as second neighbor
        rct1_atm3_key = []
        for key in atm1_nghbr_keys:
            if key != rct1_atm2_key:
                rct1_atm3_key = key
                break

        # else choose it as second neighbor to atm 2
        #print('rct1_atm2_key:', rct1_atm2_key)
        if not rct1_atm3_key:
            atm2_nghbr_keys = neighbor_dct[rct1_atm2_key]
            for key in atm2_nghbr_keys:
                if key != rct1_atm1_key:
                    rct1_atm3_key = key
                    break


        # check if rct1_atm1, rct1_atm2, rct1_atm3 are colinear
        # if they are choose a dummy atom
        rct1_geo = automol.zmatrix.geometry(rct1_zma)
        if rct1_atm3_key:
            rct1_sub_geo = (
                rct1_geo[rct1_atm1_key], rct1_geo[rct1_atm2_key], rct1_geo[rct1_atm3_key])
        else:
            rct1_sub_geo = (rct1_geo[rct1_atm1_key], rct1_geo[rct1_atm2_key])
        if automol.geom.is_linear(rct1_sub_geo) or not rct1_atm3_key:
            # have to regenerate atm2_nghbr_keys to include dummy atom keys!
            rct1_key_mat = automol.zmatrix.key_matrix(rct1_zma)
            rct1_keys = [row[0] for row in rct1_key_mat]
            atm2_nghbr_keys = [
                rct1_keys[rct1_atm2_key]] if rct1_keys[rct1_atm2_key] is not None else []
            for idx, rct1_key in enumerate(rct1_keys):
                if rct1_key == rct1_atm2_key:
                    atm2_nghbr_keys.append(idx)
            new_atm3 = False
            for atm_key in atm2_nghbr_keys:
                if atm_key not in (rct1_atm3_key, rct1_atm1_key):
                    rct1_atm3_key = atm_key
                    new_atm3 = True
                    break
            if not new_atm3:
                # if there are no dummy atoms connected to the rct1_atm2 then
                # search for dummy atom keys connected to rct1_atm1
                # now have to regenerate atm1_nghbr_keys to include dummy atom keys!
                atm1_nghbr_keys = [
                    rct1_keys[rct1_atm1_key]] if rct1_keys[rct1_atm1_key] is not None else []
                for idx, rct1_key in enumerate(rct1_keys):
                    if rct1_key == rct1_atm1_key:
                        atm1_nghbr_keys.append(idx)
                new_atm3 = False
                for atm_key in atm1_nghbr_keys:
                    if atm_key not in (rct1_atm3_key, rct1_atm2_key):
                        rct1_atm3_key = atm_key
                        new_atm3 = True
                        break

        join_val_dct = {
            dist_name: dist_val,
            'aabs1': 85. * qcc.conversion_factor('degree', 'radian'),
            'aabs2': 85. * qcc.conversion_factor('degree', 'radian'),
            'babs1': 85. * qcc.conversion_factor('degree', 'radian'),
            'babs2': 85. * qcc.conversion_factor('degree', 'radian'),
            'babs3': 85. * qcc.conversion_factor('degree', 'radian'),
        }

        rct1_natom = automol.zmatrix.count(rct1_zma)
        rct2_natom = automol.zmatrix.count(rct2_zma)
        print('rct1_natom test:', rct1_natom)
        print('rct2_natom test:', rct2_natom)

        if rct1_natom == 1 and rct2_natom == 1:
            raise NotImplementedError
        elif rct1_natom == 2 and rct2_natom == 1:
            join_keys = numpy.array(
                [[rct1_atm1_key, rct1_atm2_key, None]])
            join_names = numpy.array(
                [[dist_name, 'aabs1', None]])
        elif rct1_natom == 2 and rct2_natom == 2:
            join_keys = numpy.array(
                [[rct1_atm1_key, rct1_atm2_key, rct1_atm3_key],
                 [None, rct1_atm1_key, rct1_atm2_key]])
            join_names = numpy.array(
                [[dist_name, 'aabs1', None],
                [None, 'aabs2', 'babs2']])
        else:
            join_keys = numpy.array(
                [[rct1_atm1_key, rct1_atm2_key, rct1_atm3_key],
                 [None, rct1_atm1_key, rct1_atm2_key],
                 [None, None, rct1_atm1_key]])[:rct2_natms]
            join_names = numpy.array(
                [[dist_name, 'aabs1', 'babs1'],
                 [None, 'aabs2', 'babs2'],
                 [None, None, 'babs3']])[:rct2_natms]

        #join_keys = numpy.array(
            #[[rct1_atm1_key, rct1_atm2_key, rct1_atm3_key],
            # [None, rct1_atm1_key, rct1_atm2_key],
            # [None, None, rct1_atm1_key]])[:rct2_natms]
        #join_names = numpy.array(
            #[[dist_name, 'aabs1', 'babs1'],
             #[None, 'aabs2', 'babs2'],
             #[None, None, 'babs3']])[:rct2_natms]
        #join_names[numpy.equal(join_keys, None)] = None

        join_name_set = set(numpy.ravel(join_names)) - {None}
        join_val_dct = {name: join_val_dct[name] for name in join_name_set}


        #print('join_keys test:', join_keys)
        #print('join_names test:', join_names)
        #print('natoms test:', rct1_natom, rct2_natms)

        ts_zma = automol.zmatrix.join(
            rct1_zma, rct2_zma, join_keys, join_names, join_val_dct)

        ts_name_dct = automol.zmatrix.standard_names(ts_zma)
        dist_name = ts_name_dct[dist_name]
        #print('ts_zma:', ts_zma)
        ts_zma = automol.zmatrix.standard_form(ts_zma)
        rct1_tors_names = automol.zmatrix.torsion_coordinate_names(rct1_zma)

        if rct_tors:
            rct2_tors_names = rct_tors
        else:
            rct2_tors_names = automol.zmatrix.torsion_coordinate_names(
                rct2_zma)
        tors_names = (
            tuple(map(ts_name_dct.__getitem__, rct1_tors_names)) +
            tuple(map(ts_name_dct.__getitem__, rct2_tors_names))
        )

        if 'babs2' in ts_name_dct:
            tors_name = ts_name_dct['babs2']
            tors_names += (tors_name,)

        if 'babs3' in ts_name_dct and _include_babs3(frm_bnd_key, rct2_gra):
            tors_name = ts_name_dct['babs3']
            tors_names += (tors_name,)

        #ts_zma_p = automol.zmatrix.set_values(ts_zma, {dist_name:3.0})
        #tors_names_p = automol.zmatrix.torsion_coordinate_names(ts_zma_p)
        #ts_name_dct_p = automol.zmatrix.standard_names(ts_zma_p)
        #tors_names_add = (
        #    tuple(map(ts_name_dct_p.__getitem__, tors_names_p))
        #)
        #print('tors_names:', tors_names)
        #print('tors_names_p:', tors_names_p)
        #print('tors_names_add:', tors_names_add)
        #print('ts_zma:', ts_zma)
        ret = ts_zma, dist_name, tors_names
        print('ts_zma test:', ts_zma)
        #ret = ts_zma, dist_name, tors_names_p

    return ret


def hydrogen_abstraction(rct_zmas, prd_zmas, sigma=False):
    """ z-matrix for an abstraction reaction
    """
    if sigma:
        ret = _sigma_hydrogen_abstraction(rct_zmas, prd_zmas)
    else:
        ret = _hydrogen_abstraction(rct_zmas, prd_zmas)
    return ret


def _sigma_hydrogen_abstraction(rct_zmas, prd_zmas):
    ret = None
    dist_name = 'rts'
    dist_val = 3.

    rxn_idxs = automol.formula.reac.argsort_hydrogen_abstraction(
        list(map(automol.convert.zmatrix.formula, rct_zmas)),
        list(map(automol.convert.zmatrix.formula, prd_zmas)))
    if rxn_idxs is not None:
        rct_idxs, prd_idxs = rxn_idxs
        rct_zmas = list(map(rct_zmas.__getitem__, rct_idxs))
        prd_zmas = list(map(prd_zmas.__getitem__, prd_idxs))
        rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
        prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
        rcts_gra = functools.reduce(automol.graph.union, rct_gras)
        prds_gra = functools.reduce(automol.graph.union, prd_gras)
        tra = automol.graph.trans.hydrogen_abstraction(rcts_gra, prds_gra)
        if tra is not None:
            rct1_gra, rct2_gra = rct_gras
            rct1_zma, rct2_zma = rct_zmas
            rct1_natms = automol.zmatrix.count(rct1_zma)
            rct2_natms = automol.zmatrix.count(rct2_zma)

            frm_bnd_key, = automol.graph.trans.formed_bond_keys(tra)
            brk_bnd_key, = automol.graph.trans.broken_bond_keys(tra)
            rct1_atm1_key = next(iter(frm_bnd_key & brk_bnd_key))
            rct2_atm1_key = next(iter(frm_bnd_key - brk_bnd_key))

            # if rct1 and rct2 are isomorphic, we may get an atom key on rct2.
            # in that case, determine the equivalent atom from rct1
            if rct1_atm1_key in automol.graph.atom_keys(rct2_gra):
                atm_key_dct = automol.graph.full_isomorphism(rct2_gra,
                                                             rct1_gra)
                assert atm_key_dct
                rct1_atm1_key = atm_key_dct[rct1_atm1_key]

            rct1_atm2_key, rct1_atm3_key, _ = _join_atom_keys(
                rct1_zma, rct1_atm1_key)

            x_zma = ((('X', (None, None, None), (None, None, None)),), {})

            x_join_val_dct = {
                'rx': 1. * qcc.conversion_factor('angstrom', 'bohr'),
                'ax': 90. * qcc.conversion_factor('degree', 'radian'),
                'dx': 180. * qcc.conversion_factor('degree', 'radian'),
            }

            x_join_keys = numpy.array(
                [[rct1_atm1_key, rct1_atm2_key, rct1_atm3_key]])
            x_join_names = numpy.array([['rx', 'ax', 'dx']],
                                       dtype=numpy.object_)
            x_join_names[numpy.equal(x_join_keys, None)] = None
            x_join_name_set = set(numpy.ravel(x_join_names)) - {None}
            x_join_val_dct = {name: x_join_val_dct[name]
                              for name in x_join_name_set}
            rct1_x_zma = automol.zmatrix.join(
                rct1_zma, x_zma, x_join_keys, x_join_names, x_join_val_dct)

            rct1_x_atm_key = rct1_natms

            if rct2_atm1_key in automol.graph.atom_keys(rct1_gra):
                atm_key_dct = automol.graph.full_isomorphism(rct1_gra,
                                                             rct2_gra)
                assert atm_key_dct
                rct2_atm1_key = atm_key_dct[rct2_atm1_key]

            rct2_atm1_key -= rct1_natms
            assert rct2_atm1_key == 0
            # insert dummy atom as the second atom in reactant 2

            insert_keys = numpy.array(
                [[0, None, None],
                 [None, 1, None],
                 [None, None, 2]])[:rct2_natms]
            insert_names = numpy.array(
                [['rx2', None, None],
                 [None, 'ax2', None],
                 [None, None, 'dx2']])[:rct2_natms]
            insert_val_dct = {
                'rx2': 1. * qcc.conversion_factor('angstrom', 'bohr'),
                'ax2': 90. * qcc.conversion_factor('degree', 'radian'),
                'dx2': 180. * qcc.conversion_factor('degree', 'radian'),
            }
            insert_name_set = set(numpy.ravel(insert_names)) - {None}
            insert_val_dct = {name: insert_val_dct[name]
                              for name in insert_name_set}
            rct2_x_zma = automol.zmatrix.insert_dummy_atom(
                rct2_zma, 1, insert_keys, insert_names, insert_val_dct
            )

            join_val_dct = {
                dist_name: dist_val,
                'aabs1': 85. * qcc.conversion_factor('degree', 'radian'),
                'aabs2': 85. * qcc.conversion_factor('degree', 'radian'),
                'babs1': 170. * qcc.conversion_factor('degree', 'radian'),
                'babs2': 85. * qcc.conversion_factor('degree', 'radian'),
                'babs3': 170. * qcc.conversion_factor('degree', 'radian'),
            }

            join_keys = numpy.array(
                [[rct1_atm1_key, rct1_x_atm_key, rct1_atm2_key],
                 [None, rct1_atm1_key, rct1_x_atm_key],
                 [None, None, rct1_atm1_key]])[:rct2_natms+1]
            join_names = numpy.array(
                [[dist_name, 'aabs1', 'babs1'],
                 [None, 'aabs2', 'babs2'],
                 [None, None, 'babs3']])[:rct2_natms+1]
            join_names[numpy.equal(join_keys, None)] = None

            join_name_set = set(numpy.ravel(join_names)) - {None}
            join_val_dct = {name: join_val_dct[name] for name in join_name_set}

            ts_zma = automol.zmatrix.join(
                rct1_x_zma, rct2_x_zma, join_keys, join_names, join_val_dct)

            ts_name_dct = automol.zmatrix.standard_names(ts_zma)
            dist_name = ts_name_dct[dist_name]
            ts_zma = automol.zmatrix.standard_form(ts_zma)
            rct1_tors_names = automol.zmatrix.torsion_coordinate_names(
                rct1_zma)
            rct2_tors_names = automol.zmatrix.torsion_coordinate_names(
                rct2_zma)
            tors_names = (
                tuple(map(ts_name_dct.__getitem__, rct1_tors_names)) +
                tuple(map(ts_name_dct.__getitem__, rct2_tors_names))
            )

            if 'babs2' in ts_name_dct:
                geo1 = automol.convert.zmatrix.geometry(rct1_zma)
                if not automol.geom.is_linear(geo1):
                    tors_name = ts_name_dct['babs2']
                    tors_names += (tors_name,)

            # babs3 should only be included if there is only group
            # connected to the radical atom
            if 'babs3' in ts_name_dct and _include_babs3(frm_bnd_key, rct2_gra):
                tors_name = ts_name_dct['babs3']
                tors_names += (tors_name,)

            ret = ts_zma, dist_name, frm_bnd_key, brk_bnd_key, tors_names

    return ret


def _hydrogen_abstraction(rct_zmas, prd_zmas):
    ret = None
    dist_name = 'rts'
    dist_val = 3.

    rxn_idxs = automol.formula.reac.argsort_hydrogen_abstraction(
        list(map(automol.convert.zmatrix.formula, rct_zmas)),
        list(map(automol.convert.zmatrix.formula, prd_zmas)))
    
    # Sort so the smaller species is second (only needed for high spin rad-rad
    # count1 = automol.zmatrix.count(rct_zmas[0])
    # if len(rct_zmas) == 2:
    #     count2 = automol.zmatrix.count(rct_zmas[1])
    #     print('rct_zmas:', rct_zmas[0], rct_zmas[1])
    #     if count1 == 1 or count1 < count2:
    #         rct2_zma, rct1_zma = rct_zmas
    #         rct_zmas = [rct1_zma, rct2_zma]


    
    if rxn_idxs is not None:
        rct_idxs, prd_idxs = rxn_idxs
        rct_zmas = list(map(rct_zmas.__getitem__, rct_idxs))
        prd_zmas = list(map(prd_zmas.__getitem__, prd_idxs))
        rct2_gra = automol.zmatrix.graph(rct_zmas[1], remove_stereo=True)
        rad_atm_keys = automol.graph.resonance_dominant_radical_atom_keys(rct2_gra)
        if 0 not in rad_atm_keys:
            rct_zmas[1] = _reorder_zma_for_radicals(rct_zmas[1], min(rad_atm_keys))
            rct2_gra = automol.zmatrix.graph(rct_zmas[1], remove_stereo=True)
            rad_atm_keys = automol.graph.resonance_dominant_radical_atom_keys(rct2_gra)
            # following assert checks to ensure that the first atom in the second reactant is a radical
            # this is required for the remainder of the routine 
            assert 0 in rad_atm_keys
        rct_zmas, rct_gras = _shifted_standard_forms_with_gaphs(rct_zmas, remove_stereo=True)
        prd_zmas, prd_gras = _shifted_standard_forms_with_gaphs(prd_zmas, remove_stereo=True)
        rcts_gra = functools.reduce(automol.graph.union, rct_gras)
        prds_gra = functools.reduce(automol.graph.union, prd_gras)
        # fix to put radical atom first
        # ultimately need to fix this for multiple radical centers
        # end of fix
        tra = automol.graph.trans.hydrogen_abstraction(rcts_gra, prds_gra)
        if tra is not None:
            rct1_gra, rct2_gra = rct_gras
            rct1_zma, rct2_zma = rct_zmas
            rct1_natms = automol.zmatrix.count(rct1_zma)
            rct2_natms = automol.zmatrix.count(rct2_zma)

            frm_bnd_key, = automol.graph.trans.formed_bond_keys(tra)
            brk_bnd_key, = automol.graph.trans.broken_bond_keys(tra)
            rct1_atm1_key = next(iter(frm_bnd_key & brk_bnd_key))

            # if rct1 and rct2 are isomorphic, we may get an atom key on rct2.
            # in that case, determine the equivalent atom from rct1
            if rct1_atm1_key in automol.graph.atom_keys(rct2_gra):
                atm_key_dct = automol.graph.full_isomorphism(rct2_gra,
                                                             rct1_gra)
                assert atm_key_dct
                rct1_atm1_key = atm_key_dct[rct1_atm1_key]

            rct1_atm2_key, rct1_atm3_key, _ = _join_atom_keys(
                rct1_zma, rct1_atm1_key)

            x_zma = ((('X', (None, None, None), (None, None, None)),), {})

            abs_atm_key = ''
            for atm_key in frm_bnd_key:
                if atm_key in automol.graph.atom_keys(rct2_gra):
                    abs_atm_key = atm_key

            x_join_val_dct = {
                'rx': 1. * qcc.conversion_factor('angstrom', 'bohr'),
                'ax': 90. * qcc.conversion_factor('degree', 'radian'),
                'dx': 180. * qcc.conversion_factor('degree', 'radian'),
            }

            x_join_keys = numpy.array(
                [[rct1_atm1_key, rct1_atm2_key, rct1_atm3_key]])
            x_join_names = numpy.array([['rx', 'ax', 'dx']],
                                       dtype=numpy.object_)
            x_join_names[numpy.equal(x_join_keys, None)] = None
            x_join_name_set = set(numpy.ravel(x_join_names)) - {None}
            x_join_val_dct = {name: x_join_val_dct[name]
                              for name in x_join_name_set}
            rct1_x_zma = automol.zmatrix.join(
                rct1_zma, x_zma, x_join_keys, x_join_names, x_join_val_dct)

            x_atm_key = rct1_natms

            join_val_dct = {
                dist_name: dist_val,
                'aabs1': 85. * qcc.conversion_factor('degree', 'radian'),
                'aabs2': 85. * qcc.conversion_factor('degree', 'radian'),
                'babs1': 170. * qcc.conversion_factor('degree', 'radian'),
                'babs2': 85. * qcc.conversion_factor('degree', 'radian'),
                'babs3': 85. * qcc.conversion_factor('degree', 'radian'),
            }

            join_keys = numpy.array(
                [[rct1_atm1_key, x_atm_key, rct1_atm2_key],
                 [None, rct1_atm1_key, x_atm_key],
                 [None, None, rct1_atm1_key]])[:rct2_natms]
            join_names = numpy.array(
                [[dist_name, 'aabs1', 'babs1'],
                 [None, 'aabs2', 'babs2'],
                 [None, None, 'babs3']])[:rct2_natms]
            join_names[numpy.equal(join_keys, None)] = None

            join_name_set = set(numpy.ravel(join_names)) - {None}
            join_val_dct = {name: join_val_dct[name] for name in join_name_set}

            ts_zma = automol.zmatrix.join(
                rct1_x_zma, rct2_zma, join_keys, join_names, join_val_dct)

            ts_name_dct = automol.zmatrix.standard_names(ts_zma)
            dist_name = ts_name_dct[dist_name]
            ts_zma = automol.zmatrix.standard_form(ts_zma)
            rct1_tors_names = automol.zmatrix.torsion_coordinate_names(
                rct1_zma)
            rct2_tors_names = automol.zmatrix.torsion_coordinate_names(
                rct2_zma)
            tors_names = (
                tuple(map(ts_name_dct.__getitem__, rct1_tors_names)) +
                tuple(map(ts_name_dct.__getitem__, rct2_tors_names))
            )

            if 'babs2' in ts_name_dct:
                geo1 = automol.convert.zmatrix.geometry(rct1_zma)
                if not automol.geom.is_linear(geo1):
                    tors_name = ts_name_dct['babs2']
                    tors_names += (tors_name,)

            if 'babs3' in ts_name_dct and _include_babs3(frm_bnd_key, rct2_gra):
                tors_name = ts_name_dct['babs3']
                tors_names += (tors_name,)

            ret = ts_zma, dist_name, frm_bnd_key, brk_bnd_key, tors_names

    return ret


def _include_babs3(frm_bnd, rct2_gra):
    """Should we include babs3?
    """
    include_babs3 = False
    atm_ngbs = automol.graph.atom_neighbor_keys(rct2_gra)
    is_terminal = False
    for atm in list(frm_bnd):
        if atm in atm_ngbs:
            if len(atm_ngbs[atm]) == 1:
                is_terminal = True
    if len(atm_ngbs.keys()) > 2 and is_terminal:
        include_babs3 = True
    return include_babs3


def _shifted_standard_forms_with_gaphs(zmas, remove_stereo=False):
    conv = functools.partial(
        automol.convert.zmatrix.graph, remove_stereo=remove_stereo)
    gras = list(map(conv, zmas))
    shift = 0
    for idx, (zma, gra) in enumerate(zip(zmas, gras)):
        zmas[idx] = automol.zmatrix.standard_form(zma, shift=shift)
        gras[idx] = automol.graph.transform_keys(gra, lambda x: x+shift)
        shift += len(automol.graph.atoms(gra))
    zmas = tuple(zmas)
    gras = tuple(map(automol.graph.without_dummy_atoms, gras))
    return zmas, gras


def _join_atom_keys(zma, atm1_key):
    """ returns available join atom keys (if available) and a boolean
    indicating whether the atoms are in a chain or not
    """
    gra = automol.convert.zmatrix.graph(zma)
    atm1_chain = (
        automol.graph.atom_longest_chains(gra)[atm1_key])
    #print('atm1_key:', atm1_key)
    #print('zma test:', automol.zmatrix.string(zma))
    #print('gra:', gra)
    #print('atm1_chain test:', atm1_chain)
    atm1_ngb_keys = (
        automol.graph.atom_neighbor_keys(gra)[atm1_key])
    #print('atm1_ngb_keys test:', atm1_chain)
    if len(atm1_chain) == 1:
        atm2_key = None
        atm3_key = None
        chain = False
    elif len(atm1_chain) == 2 and len(atm1_ngb_keys) == 1:
        atm2_key = atm1_chain[1]
        atm3_key = None
        chain = False
    elif len(atm1_chain) == 2:
        atm2_key = atm1_chain[1]
        atm3_key = sorted(atm1_ngb_keys - {atm2_key})[0]
        chain = False
    else:
        atm2_key, atm3_key = atm1_chain[1:3]
        chain = True

    return atm2_key, atm3_key, chain


def _reorder_zma_for_radicals(zma, rad_idx):
    """ Creates a zmatrix where the radical atom is the first entry
        in the zmatrix
    """
    print('rad_idx test:', rad_idx)
    geo = automol.zmatrix.geometry(zma)
    geo_swp = automol.geom.swap_coordinates(geo, 0, rad_idx)
    zma_swp = automol.geom.zmatrix(geo_swp)

    return zma_swp
