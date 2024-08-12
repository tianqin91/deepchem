import os
import torch
import numpy as np
from typing import List, Sequence, Dict
from deepchem.utils.dft_utils import BaseGrid, RadialGrid


class LebedevLoader(object):
    """load the lebedev points and save the cache to save time

    Examples
    --------
    >>> from deepchem.utils.dft_utils import LebedevLoader
    >>> grid = LebedevLoader.load(3)
    >>> grid.shape
    (6, 3)

    """
    caches: Dict[int, np.ndarray] = {}

    @classmethod
    def load(cls, prec: int) -> np.ndarray:
        """Load the Lebedev grid points with the given precision.

        Parameters
        ----------
        prec: int
            Precision of the Lebedev grid. Must be an odd number between 3 and 131.

        Returns
        -------
        np.ndarray
            Lebedev grid points with shape (nphitheta, 3), where nphitheta
            is the number of points in the grid. The first two columns
            are the polar and azimuthal angles in radians, and the last
            column is the integration weights.

        """
        if prec not in cls.caches:
            # load the lebedev grid points
            dset_path = os.path.join(
                os.path.split(__file__)[0], "lebedevquad",
                "lebedev_%03d.txt" % prec)
            assert os.path.exists(
                dset_path), "The dataset lebedev_%03d.txt does not exist" % prec
            lebedev_dsets = np.loadtxt(dset_path)
            lebedev_dsets[:, :2] *= (np.pi / 180
                                    )  # convert the angles to radians
            # save to the cache
            cls.caches[prec] = lebedev_dsets

        return cls.caches[prec]


class LebedevGrid(BaseGrid):
    """Using Lebedev predefined angular points + radial grid to form 3D grid.

    Lebedev grids. These are specially-constructed grids for quadrature
    on the surface of a sphere,543, 541, 542, 540 based on the octahedral
    point group.

    Examples
    --------
    >>> from deepchem.utils.dft_utils import RadialGrid, LebedevGrid
    >>> grid = RadialGrid(100, grid_integrator="chebyshev",
    ...                   grid_transform="logm3")
    >>> l_grid = LebedevGrid(grid, 3)
    >>> l_grid.get_rgrid().shape
    torch.Size([600, 3])
    >>> grid.get_rgrid().shape
    torch.Size([100, 1])

    """

    def __init__(self, radgrid: RadialGrid, prec: int) -> None:
        """Initialize the Lebedev grid. The grid points are generated by
        combining the radial grid with the Lebedev angular points.

        Parameters
        ----------
        radgrid: RadialGrid
            Radial grid used to generate the Lebedev grid.
        prec: int
            Precision of the Lebedev grid. Must be an odd number between 3 and 131.

        """
        self._dtype = radgrid.dtype
        self._device = radgrid.device

        assert (prec % 2
                == 1) and (3 <= prec <= 131
                          ), "Precision must be an odd number between 3 and 131"

        # load the Lebedev grid points
        lebedev_dsets = torch.tensor(LebedevLoader.load(prec),
                                     dtype=self._dtype,
                                     device=self._device)
        wphitheta = lebedev_dsets[:, -1]  # (nphitheta)
        phi = lebedev_dsets[:, 0]
        theta = lebedev_dsets[:, 1]

        # get the radial grid
        assert radgrid.coord_type == "radial"
        r = radgrid.get_rgrid().unsqueeze(-1)  # (nr, 1)

        # get the cartesian coordinate
        rsintheta = r * torch.sin(theta)
        x = (rsintheta * torch.cos(phi)).view(-1, 1)  # (nr * nphitheta, 1)
        y = (rsintheta * torch.sin(phi)).view(-1, 1)
        z = (r * torch.cos(theta)).view(-1, 1)
        xyz = torch.cat((x, y, z), dim=-1)  # (nr * nphitheta, ndim)
        self._xyz = xyz

        # calculate the dvolume (integration weights)
        dvol_rad = radgrid.get_dvolume().unsqueeze(-1)  # (nr, 1)
        self._dvolume = (dvol_rad * wphitheta).view(-1)  # (nr * nphitheta)

    def get_rgrid(self) -> torch.Tensor:
        """Get the 3D grid points in Cartesian coordinates.

        Returns
        -------
        torch.Tensor
            3D grid points in Cartesian coordinates with shape (ngrid, 3).

        """
        return self._xyz

    def get_dvolume(self) -> torch.Tensor:
        """Get the integration weights for the 3D grid points.

        Returns
        -------
        torch.Tensor
            Integration weights for the 3D grid points with shape (ngrid,).

        """
        return self._dvolume

    @property
    def coord_type(self) -> str:
        """Return the coordinate type of the grid.

        Returns
        -------
        str
            Coordinate type of the grid. Always 'cart'.

        """
        return "cart"

    @property
    def dtype(self) -> torch.dtype:
        """Return the data type of the grid.

        Returns
        -------
        torch.dtype
            Data type of the grid.

        """
        return self._dtype

    @property
    def device(self) -> torch.device:
        """Return the device of the grid.

        Returns
        -------
        torch.device
            Device of the grid.

        """
        return self._device

    def getparamnames(self, methodname: str, prefix: str = "") -> List[str]:
        """Return the parameter names for serialization.

        Parameters
        ----------
        methodname: str
            Method name.
        prefix: str (default '')
            Prefix to be added to the parameter names.

        Returns
        -------
        List[str]
            List of parameter names.

        """
        if methodname == "get_rgrid":
            return [prefix + "_xyz"]
        elif methodname == "get_dvolume":
            return [prefix + "_dvolume"]
        else:
            raise KeyError("Invalid methodname: %s" % methodname)


class TruncatedLebedevGrid(LebedevGrid):
    """A class to represent the truncated lebedev grid. It is represented
    by various radial grid (usually the sliced ones) with different precisions.

    Examples
    --------
    >>> from deepchem.utils.dft_utils import RadialGrid, TruncatedLebedevGrid
    >>> grid = RadialGrid(100, grid_integrator="chebyshev",
    ...                   grid_transform="logm3")
    >>> l_grid = TruncatedLebedevGrid([grid, grid], [3, 5])
    >>> l_grid.get_rgrid().shape
    torch.Size([2000, 3])
    >>> grid.get_rgrid().shape
    torch.Size([100, 1])

    """

    def __init__(self, radgrids: Sequence[RadialGrid], precs: Sequence[int]):
        """Initialize the truncated Lebedev grid.

        Parameters
        ----------
        radgrids: Sequence[RadialGrid]
            A list of radial grids used to generate the Lebedev grid.
        precs: Sequence[int]
            A list of precisions of the Lebedev grid. Must be odd numbers
            between 3 and 131.

        """
        assert len(radgrids) == len(precs)
        assert len(precs) > 0
        self.lebedevs = [
            LebedevGrid(radgrid, prec)
            for (radgrid, prec) in zip(radgrids, precs)
        ]
        grid0 = self.lebedevs[0]

        # set the variables to be used in the properties
        self._dtype = grid0.dtype
        self._device = grid0.device
        self._xyz = torch.cat(tuple(grid.get_rgrid() for grid in self.lebedevs),
                              dim=0)
        self._dvolume = torch.cat(tuple(
            grid.get_dvolume() for grid in self.lebedevs),
                                  dim=0)
