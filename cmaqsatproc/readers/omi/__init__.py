__all__ = ['OMIL2', 'OMNO2', 'OMHCHO', 'OMPROFOZ', 'OMO3PR']

from ..core import satellite
from ...utils import walk_groups


class OMIL2(satellite):
    __doc__ = """
    Default OMI satellite processor.
    * bbox subsets the nTimes and nTimes_1  dimensions
    """

    @classmethod
    def _open_hierarchical_dataset(cls, path, bbox=None, **kwargs):
        import netCDF4
        import xarray as xr
        import re
        tmpf = netCDF4.Dataset(path)
        struct = tmpf['HDFEOS INFORMATION/StructMetadata.0'][:]
        dimassignments = {}
        # DataFieldName="O3TotalColumn"
        # DimList=("nTimes","nXtrack")

        ore = re.compile('OBJECT=.*?END_OBJECT', re.MULTILINE | re.S)
        for i in ore.findall(struct):
            # Get FieldName and DimList
            # Never let a dimension be named +1 or _1
            # (e.g., nTimes+1, nTimes_1, or nTimesp1)
            # use _1 to be consistent
            namedim = '\n,'.join([
                l.strip().replace('+1', '_1').replace('p1', '_1')
                for l in i.split('\n')
                if 'DimList=' in l or 'FieldName' in l
            ])
            if 'DimList' in namedim and 'FieldName' in namedim:
                namedimd = eval('dict(' + namedim + ')')
                for fn in namedimd:
                    if fn.endswith('FieldName'):
                        break
                else:
                    raise KeyError(f'No field name in {sorted(namedimd)}')
                dimv = namedimd['DimList']
                if isinstance(dimv, str):
                    if dimv.isnumeric():
                        dimv = 'n' + dimv
                    dimv = (dimv,)
                dimassignments[namedimd[fn]] = dimv

        uniqdims = set()
        for vark, dimset in dimassignments.items():
            uniqdims = uniqdims.union(dimset)

        datakey, = [
            gk for gk in walk_groups(tmpf, '') if gk.endswith('Data Fields')
        ]
        geokey, = [
            gk for gk in walk_groups(tmpf, '')
            if gk.endswith('Geolocation Fields')
        ]
        del tmpf
        datads = xr.open_dataset(path, group=datakey, **kwargs)
        geods = xr.open_dataset(path, group=geokey, **kwargs)

        redatadims = {}
        regeodims = {}
        for dimk in uniqdims:
            for vark, dimset in dimassignments.items():
                if vark in datads and dimk in dimset:
                    tmpvar = datads[vark]
                    for di, dk in enumerate(dimset):
                        if dimk == dk:
                            phonydk = tmpvar.dims[di]
                            redatadims[phonydk] = dimk

            for vark, dimset in dimassignments.items():
                if vark in geods and dimk in dimset:
                    tmpvar = geods[vark]
                    for di, dk in enumerate(dimset):
                        if dimk == dk:
                            phonydk = tmpvar.dims[di]
                            regeodims[phonydk] = dimk

        ds = xr.merge([datads.rename(**redatadims), geods.rename(**regeodims)])
        ds = cls.prep_dataset(ds, bbox=bbox, path=path)
        sat = cls()
        sat.path = path
        sat.ds = ds
        sat.bbox = bbox
        return sat

    @classmethod
    def prep_dataset(cls, ds, bbox=None, path=None):
        if bbox is not None:
            swlon, swlat, nelon, nelat = bbox
            df = ds[['Latitude', 'Longitude']].to_dataframe()
            df = df.query(
                f'Latitude >= {swlat} and Latitude <= {nelat}'
                + f' and Longitude >= {swlon} and Longitude <= {nelon}'
            )
            times = df.index.get_level_values('nTimes').unique()
            if len(times) < 0:
                raise ValueError(f'{path} has no values in {bbox}')
            ds = ds.isel(
                nTimes=slice(times.min(), times.max() + 1)
            )
            if 'nTimes_1' in ds.dims:
                ds = ds.isel(nTimes_1=slice(times.min(), times.max() + 2))
        return ds

    @classmethod
    def open_dataset(cls, path, bbox=None, **kwargs):
        """
        Arguments
        ---------
        path : str
            Path to a OMI OpenDAP-style file
        bbox : iterable
            swlon, swlat, nelon, nelat in decimal degrees East and North
            of 0, 0
        kwargs : mappable
            Passed to xarray.open_dataset

        Returns
        -------
        sat: OMIL2
            Satellite processing instance
        """
        import xarray as xr

        ds = xr.open_dataset(path, **kwargs).reset_coords()
        if len(ds.dims) == 0:
            return cls._open_hierarchical_dataset(path, bbox=bbox, **kwargs)
        ds = cls.prep_dataset(ds, bbox=bbox, path=path)
        sat = cls()
        sat.path = path
        sat.ds = ds
        sat.bbox = bbox
        return sat

    @classmethod
    def shorten_name(cls, key):
        key = key.replace(
            'ReferenceSectorCorrectedVerticalColumn', 'RefSctCor_VCD'
        )
        key = key.replace('SlantColumnAmount', 'SCD')
        key = key.replace('ColumnAmount', 'VCD')
        key = key.replace('Pressure', 'Press')
        key = key.replace('Scattering', 'Scat')
        key = key.replace('Altitude', 'Alt')
        key = key.replace('Spacecraft', 'Craft')
        key = key.replace('Wavelength', 'WvLen')
        key = key.replace('Registration', 'Reg')
        key = key.replace('Viewing', 'View')
        key = key.replace('Angle', 'Ang')
        key = key.replace('Pixel', 'Pix')
        key = key.replace('Measurement', 'Msrmt')
        key = key.replace('Radiance', 'Rad')
        key = key.replace('Latitude', 'Lat')
        key = key.replace('Longitude', 'Lon')
        key = key.replace('Check', 'Chk')
        key = key.replace('Fraction', 'Frac')
        key = key.replace('Configuration', 'Cfg')
        key = key.replace('Pointer', 'Ptr')
        key = key.replace('CloudRadianceFraction', 'CldRadFrac')
        key = key.replace('QualityFlags', 'QAFlag')
        key = key.replace('TerrainReflectivity', 'TerrainRefl')
        key = key.replace('ClimatologyLevels', 'ClimPresLevels')
        return key


class OMNO2(OMIL2):
    __doc__ = """
    OMNO2 satellite processor.
    * bbox subsets the nTimes and nTimes_1 dimensions
    * valid based three conditions
      * (VcdQualityFlags & 1) == 0
      * XTrackQualityFlags == 0
      * CloudFraction <= 0.3
    """
    _defaultkeys = (
        'ColumnAmountNO2Trop', 'AmfTrop', 'ColumnAmountNO2Trop', 'AmfTrop',
        'ScatteringWeight', 'ScatteringWtPressure', 'TropopausePressure',
        'TerrainPressure',
    )

    @classmethod
    def cmr_links(cls, method='opendap', **kwds):
        kwds.setdefault('short_name', 'OMNO2')
        return OMIL2.cmr_links(method=method, **kwds)

    @classmethod
    def open_dataset(cls, path, bbox=None, **kwargs):
        """
        Arguments
        ---------
        path : str
            Path to a TropOMI OpenDAP-style file
        bbox : iterable
            swlon, swlat, nelon, nelat in decimal degrees East and North
            of 0, 0
        kwargs : mappable
            Passed to xarray.open_dataset

        Returns
        -------
        sat: OMINO2
            Satellite processing instance
        """
        omtmp = OMIL2.open_dataset(path, bbox=bbox, **kwargs)
        ds = omtmp.ds
        ds['cn_x'] = ds['Longitude']
        ds['cn_y'] = ds['Latitude']
        corners = {
            'll': 0, 'lu': 3, 'ul': 1, 'uu': 2,
        }
        for key, corner in corners.items():
            ds[f'{key}_x'] = ds['FoV75CornerLongitude'].sel(nCorners=corner)
            ds[f'{key}_y'] = ds['FoV75CornerLatitude'].sel(nCorners=corner)

        ds['valid'] = (
            ((ds['VcdQualityFlags'].astype('i') & 1) == 0)
            & (ds['XTrackQualityFlags'] == 0)
            & (ds['CloudFraction'] <= 0.3)
        )
        if bbox is not None:
            swlon, swlat, nelon, nelat = bbox
            ds['valid'] = (
                ds['valid']
                & (ds['Latitude'] >= swlat) & (ds['Latitude'] <= nelat)
                & (ds['Longitude'] >= swlon) & (ds['Longitude'] <= nelon)
            )

        if not ds['valid'].any():
            import warnings
            warnings.warn('No valid pixels')

        sat = cls()
        sat.path = path
        sat.ds = ds
        sat.bbox = bbox
        return sat

    @classmethod
    def cmaq_sw(cls, overf, satl3f):
        from ...utils import coord_interp
        qpres_hpa = overf['PRES'] / 100
        sat_press = satl3f['ScatteringWtPressure'].copy()
        # No need to overwrite surface pressure
        # numpy.interp automatically extends the lowest level
        # sat_press.isel(nPresLevels=0)[:] = qpres_hpa.isel(LAY=0)
        introp = satl3f['TropopausePressure'] < qpres_hpa
        q_sw = coord_interp(
            qpres_hpa,
            sat_press,
            satl3f['ScatteringWeight'],
            indim='nPresLevels', outdim='LAY', ascending=False,
        ).where(introp)
        return q_sw

    @classmethod
    def cmaq_amf(cls, overf, satl3f, key='NO2_PER_CM2'):
        q_sw = cls.cmaq_sw(overf, satl3f)
        q_var = overf[key].where(~q_sw.isnull())
        denom = q_var.sum('LAY')
        cmaqamf = (q_sw * q_var).sum('LAY') / denom
        return cmaqamf.where(denom != 0)

    @classmethod
    def cmaq_ak(cls, overf, satl3f):
        q_sw = cls.cmaq_sw(overf, satl3f)
        q_ak = q_sw / satl3f['AmfTrop']
        return q_ak

    @classmethod
    def cmaq_process(cls, qf, satl3f):
        """
        """
        # OMI is on the aura satellite, so we create an average overpass
        overf = qf.csp.mean_overpass(satellite='aura')
        n_per_m2 = overf.csp.mole_per_m2(add=True)
        if overf['NO2'].units.strip().startswith('ppm'):
            vmr = overf['NO2'] / 1e6
        if overf['NO2'].units.strip().startswith('ppb'):
            vmr = overf['NO2'] / 1e9
        if overf['NO2'].units.strip().startswith('ppt'):
            vmr = overf['NO2'] / 1e12
        overf['NO2_PER_CM2'] = n_per_m2 * vmr * 6.022e23 / 1e4
        overf['NO2_PER_CM2'].attrs.update(overf['NO2'].attrs)
        overf['NO2_PER_CM2'].attrs['units'] = '1/cm**2'
        ak = overf['AK_CMAQ'] = cls.cmaq_ak(overf, satl3f)
        overf['ScatWt_CMAQ'] = cls.cmaq_sw(overf, satl3f)
        # uses AK for tropopause
        overf['VCDNO2_CMAQ'] = overf.csp.apply_ak('NO2_PER_CM2', ak / ak)
        # uses AK for vertical weighting
        overf['VCDNO2_CMAQ_OMI'] = overf.csp.apply_ak('NO2_PER_CM2', ak)
        # Recalculate satellite
        amf = overf['AmfTropCMAQ'] = cls.cmaq_amf(overf, satl3f)
        overf['VCDNO2_OMI_CMAQ'] = (
            satl3f['ColumnAmountNO2Trop'] * satl3f['AmfTrop'] / amf
        )
        return overf


class OMHCHO(OMIL2):
    __doc__ = """
    OMHCHO satellite processor.
    * bbox subsets the nTimes and nTimes_1 dimensions
    * valid based three conditions
      * MainDataQualityFlag == 0
      * (XtrackQualityFlagsExpanded & 1) == 0
      * AMFCloudFraction <= 0.3
    """
    _defaultkeys = (
        'ColumnAmount', 'ReferenceSectorCorrectedVerticalColumn',
        'AirMassFactor', 'ScatteringWeights', 'ClimatologyLevels'
    )

    @classmethod
    def cmr_links(cls, method='opendap', **kwds):
        kwds.setdefault('short_name', 'OMHCHO')
        return OMIL2.cmr_links(method=method, **kwds)

    @classmethod
    def open_dataset(cls, path, bbox=None, **kwargs):
        """
        Arguments
        ---------
        path : str
            Path to a TropOMI OpenDAP-style file
        bbox : iterable
            swlon, swlat, nelon, nelat in decimal degrees East and North
            of 0, 0
        kwargs : mappable
            Passed to xarray.open_dataset

        Returns
        -------
        sat: OMI
            Satellite processing instance
        """
        import xarray as xr
        omtmp = OMIL2.open_dataset(path, bbox=bbox, **kwargs)
        ds = omtmp.ds
        ds['valid'] = (
            (ds['MainDataQualityFlag'] == 0)
            & ((ds['XtrackQualityFlagsExpanded'].astype('i') & 1) == 0)
            & (ds['AMFCloudFraction'] <= 0.3)
        )
        ds['cn_x'] = ds['Longitude']
        ds['cn_y'] = ds['Latitude']

        if bbox is not None:
            swlon, swlat, nelon, nelat = bbox
            ds['valid'] = (
                ds['valid']
                & (ds['Latitude'] >= swlat) & (ds['Latitude'] <= nelat)
                & (ds['Longitude'] >= swlon) & (ds['Longitude'] <= nelon)
            )
        corners = {
            'll': (slice(None, -1), slice(None, -1)),
            'ul': (slice(None, -1), slice(1, None)),
            'lu': (slice(1, None), slice(None, -1)),
            'uu': (slice(1, None), slice(1, None)),
        }
        for key, (tslice, xslice) in corners.items():
            ds[f'{key}_x'] = xr.DataArray(
                ds['PixelCornerLongitudes'].isel(
                    nTimes_1=tslice, nXtrack_1=xslice
                ).transpose('nTimes_1', 'nXtrack_1').values,
                dims=('nTimes', 'nXtrack')
            )
            ds[f'{key}_y'] = xr.DataArray(
                ds['PixelCornerLatitudes'].isel(
                    nTimes_1=tslice, nXtrack_1=xslice
                ).transpose('nTimes_1', 'nXtrack_1').values,
                dims=('nTimes', 'nXtrack')
            )

        if not ds['valid'].any():
            raise ValueError(f'No valid pixels in {path} with {bbox}')
        sat = cls()
        sat.ds = ds
        sat.bbox = bbox
        return sat

    @classmethod
    def cmaq_sw(cls, overf, satl3f):
        from ...utils import coord_interp
        qpres_hpa = overf['PRES'] / 100
        sat_press = satl3f['ClimatologyLevels'].copy()
        sat_press.isel(nLevels=0)[:] = qpres_hpa.isel(LAY=0)
        q_sw = coord_interp(
            qpres_hpa,
            sat_press,
            satl3f['ScatteringWeights'],
            indim='nLevels', outdim='LAY', ascending=False,
        )
        return q_sw

    @classmethod
    def cmaq_amf(cls, overf, satl3f, key='FORM_PER_M2'):
        q_sw = cls.cmaq_sw(overf, satl3f)
        q_var = overf[key].where(~q_sw.isnull())
        denom = q_var.sum('LAY')
        cmaqamf = (q_sw * q_var).sum('LAY') / denom
        return cmaqamf.where(denom != 0)

    @classmethod
    def cmaq_ak(cls, overf, satl3f):
        q_sw = cls.cmaq_sw(overf, satl3f)
        q_ak = q_sw / satl3f['AirMassFactor']
        return q_ak

    @classmethod
    def cmaq_process(cls, qf, satl3f):
        """
        """
        # OMI is on the aura satellite, so we create an average overpass
        overf = qf.csp.mean_overpass(satellite='aura')
        n_per_m2 = overf.csp.mole_per_m2(add=True)
        overf['FORM_PER_M2'] = n_per_m2 * overf['FORM'] / 1e6

        ak = overf['FORM_AK_CMAQ'] = cls.cmaq_ak(overf, satl3f)
        overf['FORM_SW_CMAQ'] = cls.cmaq_sw(overf, satl3f)
        # uses AK for tropopause
        overf['VCDFORM_CMAQ'] = overf.csp.apply_ak('FORM_PER_M2', ak / ak)
        # uses AK for vertical weighting
        overf['VCDFORM_CMAQ_OMI'] = overf.csp.apply_ak('FORM_PER_M2', ak)
        # Recalculate satellite
        amf = overf['AMF_CMAQ'] = cls.cmaq_amf(overf, satl3f)

        overf['VCDHCHO_OMI_CMAQ'] = (
            satl3f['ColumnAmount'] * satl3f['AirMassFactor'] / amf
        )

        return overf


class OMO3PR(OMIL2):
    __doc__ = """
    OMO3PR satellite processor.
    * bbox subsets the nTimes and nTimes_1 dimensions
    * valid based three conditions
      * MainDataQualityFlag == 0
      * (XtrackQualityFlagsExpanded & 1) == 0
      * AMFCloudFraction <= 0.3
    """
    _defaultkeys = (
        'O3', 'AveragingKernel', 'O3APriori', 'Pressure'
    )

    @classmethod
    def cmr_links(cls, method='opendap', **kwds):
        kwds.setdefault('short_name', 'OMO3PR')
        return OMIL2.cmr_links(method=method, **kwds)

    @classmethod
    def open_dataset(cls, path, bbox=None, **kwargs):
        """
        Arguments
        ---------
        path : str
            Path to a TropOMI OpenDAP-style file
        bbox : iterable
            swlon, swlat, nelon, nelat in decimal degrees East and North
            of 0, 0
        kwargs : mappable
            Passed to xarray.open_dataset

        Returns
        -------
        sat: OMI
            Satellite processing instance
        """
        import xarray as xr
        import numpy as np

        omtmp = OMIL2.open_dataset(path, bbox=bbox, **kwargs)
        ds = omtmp.ds
        ds['valid'] = ~(ds['O3'].isnull().all('nLayers'))
        ds['cn_x'] = ds['Longitude']
        ds['cn_y'] = ds['Latitude']

        if bbox is not None:
            swlon, swlat, nelon, nelat = bbox
            ds['valid'] = (
                ds['valid']
                & (ds['Latitude'] >= swlat) & (ds['Latitude'] <= nelat)
                & (ds['Longitude'] >= swlon) & (ds['Longitude'] <= nelon)
            )

        times = ds.nTimes.values
        times_edges = xr.DataArray(
            np.concatenate([times[:1], times[1:] - 0.5, times[-1:]]),
            dims=('nTimes_1',)
        )
        xtrack = ds.nXtrack.values
        xtrack_edges = xr.DataArray(
            np.concatenate([xtrack[:1], xtrack[1:] - 0.5, xtrack[-1:]]),
            dims=('nXtrack_1',)
        )
        lat_edges = ds.Latitude.interp(
            nTimes=times_edges,
            nXtrack=xtrack_edges,
        )
        lon_edges = ds.Longitude.interp(
            nTimes=times_edges,
            nXtrack=xtrack_edges,
        )

        corners = {
            'll': (slice(None, -1), slice(None, -1)),
            'ul': (slice(None, -1), slice(1, None)),
            'lu': (slice(1, None), slice(None, -1)),
            'uu': (slice(1, None), slice(1, None)),
        }
        for key, (tslice, xslice) in corners.items():
            ds[f'{key}_x'] = xr.DataArray(
                lon_edges.isel(
                    nTimes_1=tslice, nXtrack_1=xslice
                ).transpose('nTimes_1', 'nXtrack_1').values,
                dims=('nTimes', 'nXtrack')
            )
            ds[f'{key}_y'] = xr.DataArray(
                lat_edges.isel(
                    nTimes_1=tslice, nXtrack_1=xslice
                ).transpose('nTimes_1', 'nXtrack_1').values,
                dims=('nTimes', 'nXtrack')
            )
        """
        o3du = ds['O3'].sel(nLayers=[15, 16])
        dp = ds['Pressure'].sel(nLevels=slice(15, 17)).diff('nLevels')
        airn_per_m2 = dp * 100 / 0.0289 / 9.80665
        o3n_per_m3 = o3du * 1e-5 * 101325. / 273.15 / 8.314
        o3vmr = o3n_per_m3 / airn_per_m2.values
        o3ppm = (o3vmr * 1e6).mean('nLayers')
        o3ppm.attrs.update(ds['O3'].attrs)
        o3ppm.attrs['units'] = 'ppm'
        ds['O3_500hPa_ppm'] = o3ppm
        """
        if not ds['valid'].any():
            raise ValueError(f'No valid pixels in {path} with {bbox}')
        sat = cls()
        sat.ds = ds
        sat.bbox = bbox
        return sat


class OMPROFOZ(OMIL2):
    __doc__ = """
    OMPROFOZ satellite processor.
    * bbox subsets the nTimes and nTimes_1 dimensions
    * valid based three conditions
      * MainDataQualityFlag == 0
      * (XtrackQualityFlagsExpanded & 1) == 0
      * AMFCloudFraction <= 0.3
    """
    _defaultkeys = (
        'O3TotalColumn', 'O3TroposphericColumn', 'O3Retrieved500hPa'
        'AirMassFactor', 'ScatteringWeights', 'ClimatologyLevels'
    )

    @classmethod
    def cmr_links(cls, method='opendap', **kwds):
        kwds.setdefault('short_name', 'OMHCHO')
        return OMIL2.cmr_links(method=method, **kwds)

    @classmethod
    def open_dataset(cls, path, bbox=None, **kwargs):
        """
        Arguments
        ---------
        path : str
            Path to a TropOMI OpenDAP-style file
        bbox : iterable
            swlon, swlat, nelon, nelat in decimal degrees East and North
            of 0, 0
        kwargs : mappable
            Passed to xarray.open_dataset

        Returns
        -------
        sat: OMI
            Satellite processing instance
        """
        import xarray as xr
        omtmp = OMIL2.open_dataset(path, bbox=bbox, **kwargs)
        ds = omtmp.ds
        ds['valid'] = ~(
            (ds['ExitStatus'] <= 0) | (ds['ExitStatus'] >= 10)
            | (ds['RMS'].max('nChannel') > 3)
            | (ds['AverageResiduals'].max('nChannel') >= 3)
            | (ds['EffectiveCloudFraction'] >= 0.3)
        )
        ds['cn_x'] = ds['Longitude']
        ds['cn_y'] = ds['Latitude']

        if bbox is not None:
            swlon, swlat, nelon, nelat = bbox
            ds['valid'] = (
                ds['valid']
                & (ds['Latitude'] >= swlat) & (ds['Latitude'] <= nelat)
                & (ds['Longitude'] >= swlon) & (ds['Longitude'] <= nelon)
            )
        corners = {
            'll': (slice(None, -1), slice(None, -1)),
            'ul': (slice(None, -1), slice(1, None)),
            'lu': (slice(1, None), slice(None, -1)),
            'uu': (slice(1, None), slice(1, None)),
        }
        for key, (tslice, xslice) in corners.items():
            ds[f'{key}_x'] = xr.DataArray(
                ds['LongitudePixelCorner'].isel(
                    nTimes_1=tslice, nXtrack_1=xslice
                ).transpose('nTimes_1', 'nXtrack_1').values,
                dims=('nTimes', 'nXtrack')
            )
            ds[f'{key}_y'] = xr.DataArray(
                ds['LatitudePixelCorner'].isel(
                    nTimes_1=tslice, nXtrack_1=xslice
                ).transpose('nTimes_1', 'nXtrack_1').values,
                dims=('nTimes', 'nXtrack')
            )
        ds['O3Retrieved500hPa'] = ds['O3RetrievedProfile'].sel(nLayer=22)
        dp = ds['ProfileLevelPressure'].sel(
            nLayer_1=slice(22, 24)
        ).diff('nLayer_1').sel(nLayer_1=0)
        # 1e5 m3 / m2 * 1e-5 * kg / m / s2 / K / (kg m2 / s2 / mol / K)
        #                    * kg     / s2 / K / kg / m2 * s2 * mol * K
        #                                           / m2      * mol
        o3n_per_m2 = ds['O3Retrieved500hPa'] * 1e-5 * 101325. / 273.15 / 8.314
        airn_per_m2 = dp / 9.80665 / 0.0289 * 100
        o3ppm = o3n_per_m2 / airn_per_m2 * 1e6
        o3ppm.attrs.update(ds['O3Retrieved500hPa'].attrs)
        o3ppm.attrs['units'] = 'ppm'
        ds['O3Retrieved500hPa_ppm'] = o3ppm
        if not ds['valid'].any():
            raise ValueError(f'No valid pixels in {path} with {bbox}')
        sat = cls()
        sat.ds = ds
        sat.bbox = bbox
        return sat
