"""Runtime-only compatibility patches for SCDevice simulation post-processing."""


def _patch_pyepr_compatibility():
    try:
        import pandas as pd
        import pyEPR as epr
        from pyEPR.ansys import ureg
        from pyEPR.core_distributed_analysis import DistributedAnalysis
    except Exception:
        return

    if getattr(DistributedAnalysis, "_scdevice_compat_patched", False):
        return

    def variation_index(variation):
        return int(str(variation))

    def _get_lv(self, variation=None):
        if variation is None:
            return self._parse_listvariations(self._nominal_variation)
        return self._parse_listvariations(self._list_variations[variation_index(variation)])

    def get_variation_string(self, variation=None):
        if variation is None:
            return self._nominal_variation
        return self._list_variations[variation_index(variation)]

    def get_mesh_statistics(self, variation="0"):
        return self.setup.get_mesh_stats(self._list_variations[variation_index(variation)])

    def get_convergence(self, variation="0"):
        df, _ = self.setup.get_convergence(self._list_variations[variation_index(variation)])
        return df

    def get_junctions_L_and_C(self, variation):
        if variation == "all":
            raise NotImplementedError()

        ljs = pd.Series({}, dtype="float64")
        cjs = pd.Series({}, dtype="float64")
        variables = self._hfss_variables[variation]

        for junction_name, value in self.pinfo.junctions.items():
            def parse_variable(variable_name):
                return ureg.Quantity(variables["_" + value[variable_name]]).to_base_units().magnitude

            ljs[junction_name] = parse_variable("Lj_variable")
            cjs[junction_name] = parse_variable("Cj_variable") if "Cj_variable" in value else 0

        return ljs, cjs

    DistributedAnalysis._get_lv = _get_lv
    DistributedAnalysis.get_variation_string = get_variation_string
    DistributedAnalysis.get_mesh_statistics = get_mesh_statistics
    DistributedAnalysis.get_convergence = get_convergence
    DistributedAnalysis.get_junctions_L_and_C = get_junctions_L_and_C
    DistributedAnalysis._scdevice_compat_patched = True
    epr.config.ansys.save_mesh_stats = False


_patch_pyepr_compatibility()
