"""Configuration roles belong to an adapter; records belong to the opened image."""

import copy

from heytap_eq import opkg

SPECIAL = "special:45"


def enco_mapping():
    return {"adapter": "Enco X4", "states": ["1", "2", "3 / 4", "5", "6", "7", "9", "8", "14"],
            "presets": [{"key": name, "title": name, "indices": list(range(start, start+9))}
                        for name, start in (("丹拿原声", 0), ("清亮高音", 9), ("纯享人声", 18),
                                            ("澎湃低音", 27), ("丹拿高解析", 36))]
                       + [{"key": SPECIAL, "title": "特殊配置 · 45", "indices": [45], "special": True}],
            "tables": [{"name": f"{region}_output{output}", "region": region, "output": str(output)}
                       for output in (2, 1) for region in ("other", "india")]}


def attach_configuration(bank, mapping=None):
    mapping = copy.deepcopy(mapping or enco_mapping())
    names = {t["name"] for t in bank["tables"]}
    for role in mapping["tables"]:
        role["output"], role["region"] = str(role["output"]), str(role["region"])
    opkg.require(isinstance(mapping.get("states"), list) and bool(mapping["states"]), "Missing state mapping")
    opkg.require({t["name"] for t in mapping["tables"]} == names, "Table role mapping differs from pointer tables")
    keys = set()
    for preset in mapping["presets"]:
        opkg.require(isinstance(preset["key"], str) and preset["key"] not in keys, "Duplicate configuration key")
        keys.add(preset["key"])
        indices = preset["indices"]
        expected = 1 if preset.get("special") else len(mapping["states"])
        opkg.require(len(indices) == expected and len(set(indices)) == expected, "Invalid configuration states")
        for table in bank["tables"]:
            opkg.require(all(type(i) is int and 0 <= i < len(table["profile_indices"]) for i in indices),
                         "Configuration index is outside actual pointer table")
    bank["configuration"] = mapping
    return bank


def configurations(bank):
    return bank["configuration"]["presets"]


def config(bank, key):
    if key == "特殊记录 45":
        key = SPECIAL
    result = next((p for p in configurations(bank) if p["key"] == key), None)
    opkg.require(result is not None, f"Unknown configuration: {key}")
    return result


def tables_for(bank, region):
    roles = bank["configuration"]["tables"]
    return [t for t in roles if t["region"] == region]


def record_at(bank, table_name, key, state=0):
    table = next(t for t in bank["tables"] if t["name"] == table_name)
    preset = config(bank, key)
    slot = preset["indices"][0 if preset.get("special") else state]
    return bank["profiles"][table["profile_indices"][slot]]


def regions(bank):
    return list(dict.fromkeys(t["region"] for t in bank["configuration"]["tables"]))
