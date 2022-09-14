__all__ = ['satellite']

from ..utils import EasyDataFramePolygon, grouped_weighted_avg, rootremover


class satellite:
    _crs = 4326
    _defaultkeys = ()
    _stdkeys = ('valid',)
    _geokeys = (
        'll_x', 'll_y',
        'lu_x', 'lu_y',
        'uu_x', 'uu_y',
        'ul_x', 'ul_y',
    )

    @classmethod
    def from_dataset(cls, ds, path='unknown'):
        """
        Arguments
        ---------
        ds : xarray.Dataset
            Satellite dataset

        Returns
        -------
        sat: satellite
            Satellite processing instance
        """
        sat = cls()
        sat.ds = ds
        sat.path = path
        sat.bbox = None
        return sat

    @classmethod
    def open_dataset(cls, path, bbox=None, **kwargs):
        """
        Arguments
        ---------
        path : str
            Path to a satellite file
        bbox : iterable
            swlon, swlat, nelon, nelat in decimal degrees East and North
            of 0, 0
        kwargs : mappable
            Passed to xarray.open_dataset

        Returns
        -------
        sat: satellite
            Satellite processing instance
        """
        import xarray as xr
        sat = cls()
        sat.path = path
        sat.ds = xr.open_dataset(path, *kwargs)
        if bbox is not None:
            import warnings
            warnings.warn(f'{cls} bbox not implemented; all cells returned')
        return sat

    @property
    def ds(self):
        return self._ds

    @ds.setter
    def ds(self, ds):
        self._ds = ds

    def to_dataframe(self, *varkeys, valid=True, geo=False):
        """
        Arguments
        ---------
        varkeys : iterable
            Keys to use in the dataframe. Defaults to class._defaultkeys that
            is class specific
        valid : bool
            If true, only return valid pixels.
        geo : bool
            Add geometry to output a geopandas.GeoDataFrame

        Returns
        -------
        df : pandas.DataFrame or geopandas.GeoDataFrame
        """
        keys = list(self._stdkeys) + list(varkeys)
        df = self.ds[keys].to_dataframe()
        if valid:
            df = df.query('valid == True')
        if not (geo is False):
            import geopandas as gpd
            if geo is True:
                geo = EasyDataFramePolygon
            gdf = self.to_dataframe(*self._geokeys, valid=valid)
            if gdf.shape[0] == 0:
                raise ValueError('No valid pixels')
            gdf = gpd.GeoDataFrame(
                gdf, geometry=geo(gdf), crs=self._crs
            ).drop(list(self._geokeys), axis=1)
            df = gdf[['geometry']].join(df)
        if 'valid' not in varkeys:
            df = df.drop('valid', axis=1)
        for key in df.columns:
            if key in self.ds.variables:
                df[key].attrs.update(self.ds[key].attrs)
        return df

    def add_weights(self, intx, option='equal'):
        """
        Add Weights to intersection dataframe (intx) using predefined options:
        * 'equal' uses equal weights for all overlapping pixels
        * 'area' uses area of intersection for all overlapping pixels
        * other methods can be added by overriding this mehtod
        """
        if option == 'equal':
            intx['weight'] = 1
        elif option == 'area':
            intx['weight'] = intx.geometry.area
        else:
            raise KeyError(f'Unknown weighting option {option}')

        return None

    def shorten_name(self, k):
        """
        By default, nothing is done and k is returned. Override this method to
        make short names
        """
        return k

    def to_level3(
        self, *varkeys, grid, griddims=None, weighting='area',
        as_dataset=False, verbose=0
    ):
        """
        Arguments
        ---------
        varkeys : iterable
            See to_dataframe
        grid : geopandas.GeoDataFrame
            Defines the grid used as the L3 destination
        griddims : iterable
            Defaults to grid.index.names
        weighting : str
            Passed as option to self.add_weights

        Returns
        -------
        outputs : dict
            Dictionary of outputs by output dimensions
        """
        import geopandas as gpd
        if len(varkeys) == 0:
            varkeys = [
                k for k in self._defaultkeys if k in list(self.ds.data_vars)
            ]
            if verbose > 0:
                print('defaults', varkeys)
        if griddims is None:
            griddims = list(grid.index.names)
        if verbose > 1:
            print('griddims', griddims)
        dimsets = {}
        for key in varkeys:
            dims = self.ds[key].dims
            dimsets.setdefault(dims, []).append(key)
        if verbose > 1:
            print('dimsets', dimsets)

        if verbose > 0:
            print('Making geometry', flush=True)
        # Index is lost during overlay, and must be recreated
        geodf = self.to_dataframe(geo=True).to_crs(grid.crs)[['geometry']]
        if verbose > 1:
            print(f'Geometry has {geodf.shape[0]} rows')
        if geodf.shape[0] == 0:
            raise ValueError('No valid pixels')
        myidx = list(geodf.index.names) + list(grid.index.names)
        if verbose > 0:
            print('Making overlay', flush=True)
        intx = gpd.overlay(
            geodf.reset_index(), grid.reset_index(), how='intersection'
        )
        intx.set_index(myidx, inplace=True)
        if verbose > 1:
            print(f'Overlay has {intx.shape[0]} rows')
        if verbose > 0:
            print('Adding weights', flush=True)
        self.add_weights(intx, option=weighting)
        overlays = {}
        for dimset, keys in dimsets.items():
            if verbose > 0:
                print('Working on', dimset, flush=True)
            outdims = griddims + [k for k in dimset if k not in myidx]
            if verbose > 1:
                print(' - Making dataframe', flush=True)
            df = self.to_dataframe(*keys, geo=False)
            if verbose > 1:
                print(' - Adding intx geometry', flush=True)
            df = intx.join(df)
            # Geometry objects are not weightable
            if verbose > 1:
                print(' - Weighting', flush=True)
            gdf = grouped_weighted_avg(
                df.drop('geometry', axis=1), df['weight'], outdims
            )
            if verbose > 1:
                print(' - Adding attributes', flush=True)
            for key in gdf.columns:
                if key in self.ds.variables:
                    gdf[key].attrs.update(self.ds[key].attrs)

            overlays[tuple(dimset)] = gdf

        if as_dataset:
            import xarray as xr
            from datetime import datetime
            dss = {}
            for dimks, outdf in overlays.items():
                dss[dimks] = xr.Dataset.from_dataframe(outdf)
            outds = xr.merge(dss.values())
            for key in outds.variables:
                if key in self.ds.variables:
                    outds[key].attrs.update(self.ds[key].attrs)
            docstr = getattr(self, '__doc__', None)
            if docstr is None:
                docstr = ""
            outds.attrs['description'] = (
                docstr
                + '\n - {}'.format(getattr(self, 'path', '<path unknown>'))
            )
            outds.attrs['updated'] = datetime.now().strftime('%FT%H:%M:%S%z')
            outds.attrs['history'] = ''
            return outds

        return overlays

    @classmethod
    def paths_to_level3(
        cls, paths, grid, griddims=None, weighting='area', bbox=None,
        verbose=0, varkeys=None, as_dataset=False, **kwargs
    ):
        """
        Iteratively apply
        output = cls(path).to_level3(*args, path=path, **kwds)
        and then grouped_weighted_avg(output[dims]) for each dimset
        """
        import pandas as pd
        from copy import copy

        if varkeys is None:
            varkeys = ()

        withdata = {}
        nodata = {}
        if griddims is None:
            griddims = list(grid.index.names)

        for path in paths:
            if verbose > 0:
                print(path)
            try:
                sat = cls.open_dataset(path, bbox=bbox, **kwargs)
                withdata[path] = sat.to_level3(
                    *varkeys, grid=grid, griddims=griddims,
                    weighting=weighting, verbose=verbose
                )
            except Exception as e:
                nodata[path] = repr(e)
                if verbose > 0:
                    print(nodata[path])

        keys = sorted(withdata)
        dimdatasets = {}
        dimpaths = {}
        for path, output in withdata.items():
            for key, valdf in output.items():
                dimdatasets.setdefault(key, []).append(valdf)
                dimpaths.setdefault(key, []).append(path)
        outputs = {}
        for dimks, dimdfs in dimdatasets.items():
            keys = dimpaths[dimks]
            attrs = {
                key: copy(dimdfs[0][key].attrs) for key in dimdfs[0].columns
            }
            combinedf = pd.concat(
                dimdfs, keys=keys, names=['path']
            )
            outdims = list(dimdfs[0].index.names)
            combinedf = grouped_weighted_avg(
                combinedf, combinedf['weight_sum'], outdims
            )
            for key in combinedf.columns:
                if key in attrs:
                    combinedf[key].attrs.update(attrs[key])
            outputs[dimks] = combinedf

        if as_dataset:
            import xarray as xr
            from datetime import datetime
            dss = {}
            for dimks, outdf in outputs.items():
                dss[dimks] = xr.Dataset.from_dataframe(outdf)
            outds = xr.merge(dss.values()).reindex(**{
                griddim: grid.index.get_level_values(griddim).unique()
                for griddim in griddims
            })
            for key in outds.variables:
                if key in sat.ds.variables:
                    outds[key].attrs.update(sat.ds[key].attrs)
            docstr = getattr(cls, '__doc__', None)
            if docstr is None:
                docstr = ""
            outds.attrs['description'] = (
                docstr
                + '\n - '.join(rootremover(paths, insert=True)[1])
            )
            outds.attrs['history'] = str(nodata)
            outds.attrs['updated'] = datetime.now().strftime('%FT%H:%M:%S%z')
            return outds

        return outputs, nodata
