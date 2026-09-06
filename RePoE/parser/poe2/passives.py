import os.path

from PyPoE.poe.file.psg2 import PSGFile
from PyPoE.poe.file.translations import TranslationFileCache
from RePoE.parser import Parser_Module
from RePoE.parser.util import call_with_default_args, write_any_json

PASSIVE_COLS = {
    "Id": "id",
    "PassiveSkillGraphId": "hash",
    "Name": "name",
    "FlavourText": "flavour_text",
    "ReminderTextKeys": "reminder_text",
    "SkillPointsGranted": "skill_points",
    "IsKeystone": "is_keystone",
    "IsNotable": "is_notable",
    "IsMultipleChoice": "is_multiple_choice",
    "IsMultipleChoiceOption": "is_multiple_choice_option",
    "IsJustIcon": "is_icon_only",
    "IsJewelSocket": "is_jewel_socket",
    "IsAscendancyStartingNode": "is_ascendancy_starting_node",
    "IsRootOfAtlasTree": "is_atlas_root",
    "AtlasnodeGroup": "atlas_group",
    "WeaponPointsGranted": "weapon_set_points",
    "IsFree": "is_free",
}


TRANSLATION_FILES = {
    "AtlasSkillTreeTitle": "atlas_stat_descriptions.txt",
    "PassiveSkillTreeTitle": "passive_skill_stat_descriptions.txt",
}


def passive(row, translation_file, lang):
    result = {k: row[col] for col, k in PASSIVE_COLS.items()}
    if row["PassiveSkillBuffs"]:
        result["buff_definitions"] = [buff["BuffDefinitionsKey"]["Id"] for buff in row["PassiveSkillBuffsKeys"]]
    if row["Ascendancy"]:
        result["ascendancy"] = row["Ascendancy"]["Id"]
    if row["Icon_DDSFile"]:
        result["icon"] = row["Icon_DDSFile"]
    if row["AtlasSubTree"]:
        result["atlas_subtree"] = row["AtlasSubTree"]["Id"]
    if row["GrantedSkill"]:
        result["granted_skill"] = row["GrantedSkill"]["BaseItemType"]["Id"]
    if row["AtlasSubTree"]:
        result["atlas_subtree"] = atlas_subtree(row["AtlasSubTree"])
    stats = dict(zip([stat["Id"] for stat in row["Stats"]], [row[f"Stat{i}Value"] for i in range(1, 5)]))
    result["stats"] = stats
    if translation_file:
        result["stat_text"] = translation_file.get_translation(stats.keys(), stats, lang=lang)
    return result


def atlas_subtree(row):
    return {
        "id": row["Id"],
        "image": row["UI_Image"],
        "background": row["UI_Background"],
        "illustration": {
            "x": row["IllustrationX"],
            "y": row["IllustrationY"],
        },
        "counter": {
            "x": row["CounterX"],
            "y": row["CounterY"],
        },
    }


def uiart(row):
    result = {"id": row["Id"], "glow": row["Glow"]}
    for size in ["Small", "Medium", "Large"]:
        for blank in [False, True]:
            result[f"group_bg_{size.lower()}_{'blank' if blank else 'normal'}"] = row[
                f"GroupBackground{size}{'Blank' if blank else ''}"
            ]
    for size in ["Passive", "Notable", "Keystone", "Jewel", "AscendancyStart"]:
        result[f"{size.lower()}_frame"] = frame_art(row[size if size == "AscendancyStart" else f"{size}Frame"])
    return result


def frame_art(row):
    if not row:
        return None
    result = {}
    for col, key in [("Normal", "unallocated"), ("Active", "allocated"), ("CanAllocate", "allocatable")]:
        result[key] = row[col]
    return result


class passives(Parser_Module):

    def write(self) -> None:
        all_passives = self.relational_reader["PassiveSkills.dat64"]
        if "PassiveSkillGraphId" not in all_passives.index:
            all_passives.build_index("PassiveSkillGraphId")
        self.index = all_passives.index["PassiveSkillGraphId"]
        for tree in self.relational_reader["PassiveSkillTrees.dat64"]:
            tf_name = TRANSLATION_FILES.get(tree["Name"]["Id"], None)
            tf = self.get_cache(TranslationFileCache)[tf_name] if tf_name else None
            psg = self.psg(tree["PassiveSkillGraph"])
            nodes = {}
            for p in psg.root_passives:
                if p not in nodes:
                    nodes[p] = passive(self.index[p], tf, self.language)
            groups = []
            for group in psg.groups:
                groups.append(
                    {
                        "x": group.x,
                        "y": group.y,
                        "flag": group.flag,
                        "passives": [
                            {
                                "hash": n.passive_skill,
                                "radius": n.radius,
                                "position_clockwise": n.position,
                                "connections": n.connections,
                                "splines": n.splines,
                            }
                            for n in group.nodes
                        ],
                    }
                )
                for node in group.nodes:
                    if node.passive_skill not in nodes:
                        nodes[node.passive_skill] = passive(self.index[node.passive_skill], tf, self.language)
            write_any_json(
                {
                    "title": tree["Name"]["Text"],
                    "roots": psg.root_passives,
                    "skills_per_orbit": psg.skills_per_orbit,
                    "orbit_radii": [0, 82, 162, 335, 493, 662, 846, 251, 1080, 1332],
                    "groups": groups,
                    "passives": nodes,
                    "art": uiart(tree["UIArt"]),
                },
                os.path.join(self.data_path, "passive_skill_trees"),
                tree["Id"],
            )

    def psg(self, filename):
        psg = PSGFile()
        psg.read(self.file_system.get_file(filename + ".psg"))
        return psg


if __name__ == "__main__":
    call_with_default_args(passives)
