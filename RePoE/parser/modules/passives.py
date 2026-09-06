import os.path

from PyPoE.poe.file.psg import PSGFile
from PyPoE.poe.file.translations import TranslationFileCache
from RePoE.parser import Parser_Module
from RePoE.parser.util import call_with_default_args, write_any_json

COLS = {
    "Id": "id",
    "PassiveSkillGraphId": "hash",
    "Name": "name",
    "FlavourText": "flavour_text",
    "ReminderTextKeys": "reminder_text",
    "SkillPointsGranted": "skill_points",
    "IsKeystone": "is_keystone",
    "IsNotable": "is_notable",
    "IsMultipleChoiceOption": "is_multiple_choice_option",
    "IsMultipleChoice": "is_multiple_choice",
    "IsJustIcon": "is_icon_only",
    "IsJewelSocket": "is_jewel_socket",
    "IsAscendancyStartingNode": "is_ascendancy_starting_node",
}

TRANSLATION_FILES = {
    "AtlasSkillTreeTitle": "atlas_stat_descriptions.txt",
    "PassiveSkillTreeTitle": "passive_skill_stat_descriptions.txt",
}

CLASS_PASSIVES = [f"AscendancySpecialEldritch{i}" for i in range(1, 6)] + ["AscendancyTrickster14"]


class passives(Parser_Module):

    def write(self) -> None:
        all_passives = self.relational_reader["PassiveSkills.dat64"]
        if "PassiveSkillGraphId" not in all_passives.index:
            all_passives.build_index("PassiveSkillGraphId")
        self.index = all_passives.index["PassiveSkillGraphId"]
        for tree in self.relational_reader["PassiveSkillTrees.dat64"]:
            tf = TRANSLATION_FILES.get(tree["Name"]["Id"], None)
            psg = self.psg(tree["PassiveSkillGraph"])
            nodes = {}
            for passive in psg.root_passives:
                if passive not in nodes:
                    nodes[passive] = self.passive(self.index[passive], tf)
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
                            }
                            for n in group.nodes
                        ],
                    }
                )
                for node in group.nodes:
                    if node.passive_skill not in nodes:
                        nodes[node.passive_skill] = self.passive(self.index[node.passive_skill], tf)
            write_any_json(
                {
                    "title": tree["Name"]["Text"],
                    "roots": psg.root_passives,
                    "groups": groups,
                    "passives": nodes,
                    "art": self.uiart(tree["UIArt"]),
                },
                os.path.join(self.data_path, "passive_skill_trees"),
                tree["Id"],
            )

    def psg(self, filename):
        psg = PSGFile()
        psg.read(self.file_system.get_file(filename + ".psg"))
        return psg

    def uiart(self, row):
        result = {"ornament": row["Ornament"]}
        bg = row["BackgroundArt"]
        for size in ["Small", "Medium", "Large"]:
            for blank in [False, True]:
                result[f"group_bg_{size.lower()}_{'blank' if blank else 'normal'}"] = bg[
                    f"{size}{'Blank' if blank else ''}"
                ]
        for size in ["Passive", "Notable", "Keystone"]:
            result[f"{size.lower()}_frame"] = {
                k: row[f"{size}Frame"][t]
                for t, k in [("Normal", "unallocated"), ("Active", "allocated"), ("CanAllocate", "allocatable")]
            }
        return result

    def passive(self, passive, translation_file):
        result = {k: passive[col] for col, k in COLS.items()}
        if passive["PassiveSkillBuffsKeys"]:
            result["buff_definitions"] = [buff["BuffDefinitionsKey"]["Id"] for buff in passive["PassiveSkillBuffsKeys"]]
        if passive["AscendancyKey"]:
            if passive["Id"] in CLASS_PASSIVES:
                result["ascendancy"] = passive["AscendancyKey"]["CharactersKey"]["Name"]
            else:
                result["ascendancy"] = passive["AscendancyKey"]["Name"]
        if passive["Icon_DDSFile"]:
            result["icon"] = passive["Icon_DDSFile"]
        stats = dict(zip([stat["Id"] for stat in passive["Stats"]], [passive[f"Stat{i}Value"] for i in range(1, 5)]))
        result["stats"] = stats
        if translation_file:
            result["stat_text"] = self.get_cache(TranslationFileCache)[translation_file].get_translation(
                stats.keys(), stats, lang=self.language
            )
        return result

    def group(self, g):
        pass


if __name__ == "__main__":
    call_with_default_args(passives)
