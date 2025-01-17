import numpy as np
import scipy

from .spectral import logical_mass_matrix, diag_logical_mass_matrix, logical_differentiation_matrix
from .interpolate import lagrange_interpolate


precomputed_massmats = {}


def mass_matrix(e, d):
    global precomputed_massmats
    p = e.num_points[d]
    if not (p in precomputed_massmats):
        precomputed_massmats[p] = logical_mass_matrix(e.collocation_points[d])
    # This way of handling the jacobian only works because it is constant for
    # our rectangular mesh.
    return e.inertial_to_logical_jacobian[d, d] * precomputed_massmats[p]


precomputed_diag_massmats = {}


def diag_mass_matrix(e, d):
    global precomputed_diag_massmats
    p = e.num_points[d]
    if not (p in precomputed_diag_massmats):
        precomputed_diag_massmats[p] = diag_logical_mass_matrix(
            e.quadrature_weights[d])
    # This way of handling the jacobian only works because it is constant for
    # our rectangular mesh.
    return e.inertial_to_logical_jacobian[d, d] * precomputed_diag_massmats[p]


precomputed_diffmats = {}


def differentiation_matrix(e, d):
    global precomputed_diffmats
    p = e.num_points[d]
    if not (p in precomputed_diffmats):
        precomputed_diffmats[p] = logical_differentiation_matrix(
            e.collocation_points[d])
    return precomputed_diffmats[p] / e.inertial_to_logical_jacobian[d, d]


def interpolation_matrix(from_points, to_points):
    return np.array([lagrange_interpolate(from_points, unit_vector)(to_points) for unit_vector in np.eye(len(from_points))]).T


def apply_matrix(O, u, d):
    return np.apply_along_axis(lambda x: O @ x, d, u)


def interpolate_to(u, e, to_points):
    valence = u.ndim - e.dim
    Iu = u
    for d in range(e.dim):
        I = interpolation_matrix(e.collocation_points[d], to_points[d])
        axis = d + valence
        Iu = apply_matrix(I, Iu, axis)
    return Iu


def interpolate_from(u, e, from_points):
    valence = u.ndim - e.dim
    Iu = u
    for d in range(e.dim):
        I = interpolation_matrix(from_points[d], e.collocation_points[d])
        axis = d + valence
        Iu = apply_matrix(I, Iu, axis)
    return Iu


def compute_deriv(u, e):
    """
    Compute the partial derivatives of the field data `u` on the element `e`.

    Parameters
    ----------
    u : array_like
        The field to differentiate.
    e : domain.Element
        The element that holds the field.
    
    Returns
    -------
    grad_u : (D,) + u.shape array_like
        The partial derivatives of `u` on `e`.
    """
    grad_u = np.zeros((e.dim, *u.shape))
    for d in range(e.dim):
        D = differentiation_matrix(e, d)
        axis = d + (u.ndim - e.dim)
        grad_u[d] = apply_matrix(D, u, axis)
    return grad_u


def compute_div(v, e):
    """
    Compute the divergence of the field data `u` on the element `e`.

    Parameters
    ----------
    u : array_like
        The field to take the divergence of. Must have valence 1 or higher.
    e : domain.Element
        The element that holds the field.
    
    Returns
    -------
    div_u : u.shape[1:] array_like
        The divergence of `u` on `e`.
    """
    div_v = np.zeros(v.shape[1:])
    for d in range(e.dim):
        D = differentiation_matrix(e, d)
        axis = d + (v.ndim - 1 - e.dim)
        div_v += apply_matrix(D, v[d], axis)
    return div_v


def compute_mass(u, e):
    Mu = u
    for d in range(e.dim):
        # M = diag_mass_matrix(e, d)
        M = mass_matrix(e, d)
        axis = (u.ndim - e.dim) + d
        Mu = apply_matrix(M, Mu, axis)
    return Mu


def compute_inverse_mass(u, e):
    Mu = u
    for d in range(e.dim):
        M = np.linalg.inv(mass_matrix(e, d))
        axis = (u.ndim - e.dim) + d
        Mu = apply_matrix(M, Mu, axis)
    return Mu


def quadrature(space, u, valence):
    data = u * space.inertial_to_logical_jacobian_det
    if space.dim > 0:
        valence_indices = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][:valence]
        summed_indices = ['i', 'j', 'k'][:space.dim]
        data = np.einsum(','.join(summed_indices) + ',' + ''.join(valence_indices + summed_indices) +
                         '...->' + ''.join(valence_indices) + '...', *space.quadrature_weights, data)
    return data


def basis_deriv(e, face=None):
    dphi = np.zeros((e.dim, *e.num_points, *e.num_points))
    for d in range(e.dim):
        dphi[d] = np.einsum(
            ','.join(['li', 'mj', 'nk'][:e.dim]) + '->' + ''.join(['l',
                                                                   'm', 'n'][:e.dim]) + ''.join(['i', 'j', 'k'][:e.dim]),
            *[differentiation_matrix(e, d) if p == d else np.eye(e.num_points[p]) for p in range(e.dim)]
        )
    if face is not None:
        dphi = dphi.take(face.slice_index(), axis=1 + face.dimension)
    return dphi


def basis(e, face=None):
    phi = np.einsum(
        ','.join(['li', 'mj', 'nk'][:e.dim]) + '->' + ''.join(['l',
                                                               'm', 'n'][:e.dim]) + ''.join(['i', 'j', 'k'][:e.dim]),
        *[np.eye(e.num_points[p]) for p in range(e.dim)]
    )
    if face is not None:
        phi = phi.take(face.slice_index(), axis=face.dimension)
    return phi


def lift_flux(u, face, scheme='mass_matrix'):
    valence = u.ndim - face.dim
    if scheme == 'quadrature':
        return quadrature(
            face,
            u.reshape(*u.shape, *((face.dim + 1) *
                                  [1])) * basis(face.element, face),
            valence
        )
    elif scheme == 'mass_matrix':
        result_slice = u
        for d in range(face.dim):
            result_slice = apply_matrix(mass_matrix(face, d), result_slice, d + valence)
        result = np.zeros(valence * (face.element.dim,) + tuple(face.element.num_points))
        slc = (slice(None),) * (valence + face.dimension) + (face.slice_index(),)
        result[slc] = result_slice
        return result
    else:
        raise NotImplementedError

def lift_deriv_flux(v, face, scheme='quadrature'):
    valence = v.ndim - 1 - face.dim
    if scheme == 'quadrature':
        v_broadcast_over_basis = v.reshape(*v.shape, *((face.dim + 1) * [1]))
        integrand = np.einsum('j...,j...', v_broadcast_over_basis, basis_deriv(face.element, face))
        return quadrature(
            face,
            integrand,
            valence
        )
    elif scheme == 'mass_matrix':
        v_lifted = lift_flux(v, face, scheme)
        result = np.zeros(v_lifted.shape[1:])
        for d in range(face.element.dim):
            result += apply_matrix(differentiation_matrix(face.element, d).T, v_lifted[d], d + valence)
        return result
    else:
        raise NotImplementedError
     
# TODO: move to IP scheme
def penalty(face, penalty_parameter):
    num_points = face.element.num_points[face.dimension]
#     p = num_points - 1
#     h = np.squeeze(np.diff(face.element.extents[face.dimension]))
    h = 2 * face.element.inertial_to_logical_jacobian[face.dimension, face.dimension]
    # H&W use "N + 1" which is num_points, but Trevor knows a paper where they show num_points-1 is sufficient
    # However: weak_primal scheme, h=2, p=6 fails for num_points-1, so using num_points for now
    return penalty_parameter * num_points**2 / h


# TODO: remove
def lift_internal_penalty(u, face, penalty_parameter):
    sigma = penalty(face, penalty_parameter)
    # exterior_face_factor = 1 if face.is_in('external') else 0.5
    return quadrature(
        face,
        u.reshape(*u.shape, *((face.dim + 1) * [1])) * (0.5 * np.einsum('d...,d...', np.reshape(face.get_normal(
        ), (face.dim + 1, *face.num_points, *((face.dim + 1) * [1]))), basis_deriv(face.element, face)) - sigma * basis(face.element, face)),
        u.ndim - face.dim
    )
