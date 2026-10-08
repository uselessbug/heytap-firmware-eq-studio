"""Enco X4 semantic recognition requires full code fingerprints and pointer checks."""

from dataclasses import dataclass

from heytap_eq import opkg

PRESETS = {"丹拿原声": 0, "清亮高音": 9, "纯享人声": 18, "澎湃低音": 27, "丹拿高解析": 36}
STATES = ("1", "2", "3 / 4", "5", "6", "7", "9", "8", "14")
FINGERPRINTS = {
    8717764: ((0x30e78, 0x31074, "b32a48278cf763913b5628d9ef1f945b66ff0b9dd070998ca35a33b5c2978dd0"),
              (0x147c4c, 0x14834c, "e061b11094721c77b44655e1b77b1f2f93b316212b69af61d7c0b8c3f3d865f6")),
    8650680: ((0x30e78, 0x31074, "5d0cb27c1e6ead6c2bc2b0b295d0d57909df3ca5515956b37cdb1b0d07adfd81"),
              (0x14a60c, 0x14ad0c, "1e40b745cf092e37de58d9150ee54a36152b00fe59685d72a49299ce325ffe16")),
}


@dataclass
class Firmware:
    path: str
    package: dict
    profiles: dict | None
    recognition: str

    @property
    def sha256(self):
        return self.package["summary"]["file_sha256"]


def inspect_firmware(path):
    item = opkg.load(path)
    raw = item["raw"]
    bank = None
    reason = "未知布局；完整性通过，结构尚未确认"
    if item["summary"]["product_id"] == "06EC10" and len(raw) in FINGERPRINTS:
        if all(opkg.sha(raw[a:b]) == digest for a, b, digest in FINGERPRINTS[len(raw)]):
            bank = opkg.profiles(raw)
            for record in bank["profiles"]:
                opkg.require(all(-60 <= record[k] <= 1 for k in ("gain0", "gain1")), "Overall gain out of known bounds")
                for f in record["slots"][:record["count"]]:
                    opkg.require(f["type_id"] <= 5 and -60 <= f["gain"] <= 24
                                 and 0 < f["fc"] < 22050 and .01 <= f["q"] <= 100,
                                 "Active filter outside known preview bounds")
            reason = "Enco X4：代码指纹与四张指针表通过；当前桌面阶段只读"
        else:
            reason = "布局长度相似，代码指纹未确认；保持只读"
    return Firmware(str(path), item, bank, reason)
