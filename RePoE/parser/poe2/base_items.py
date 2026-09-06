from collections import defaultdict
from typing import Any, Dict, Optional, List

from PyPoE.poe.file.dat import DatReader, DatRecord
from PyPoE.poe.file.it import ITFileCache
from RePoE.parser import Parser_Module
from RePoE.parser.poe2.mods import MOD_DOMAIN
from RePoE.parser.util import (
    call_with_default_args,
    export_image,
    get_release_state,
    write_json,
    write_any_json,
    compose_flask,
)


def _create_default_dict(relation: DatReader, col="BaseItemTypesKey") -> Dict:
    d = {row[col]["Id"]: row for row in relation if row[col]}
    return defaultdict(lambda: None, d)


def _add_if_greater_zero(value: int, key: str, obj: Dict[str, int]) -> None:
    if value > 0:
        obj[key] = value


def _add_if_not_zero(value: int, key: str, obj: Dict[str, Any]) -> None:
    if value != 0:
        obj[key] = value


def _convert_requirements(attribute_requirements: Optional[DatRecord], drop_level: int) -> Optional[Dict[str, int]]:
    if attribute_requirements is None:
        return None
    return {
        "strength": attribute_requirements["ReqStr"],
        "dexterity": attribute_requirements["ReqDex"],
        "intelligence": attribute_requirements["ReqInt"],
        "level": drop_level,
    }


def _convert_armour_properties(armour_row: Optional[DatRecord], properties: Dict) -> None:
    if armour_row is None:
        return
    _add_min_max(armour_row, "Armour", "armour", properties)
    _add_min_max(armour_row, "Evasion", "evasion", properties)
    _add_min_max(armour_row, "EnergyShield", "energy_shield", properties)
    _add_if_not_zero(armour_row["IncreasedMovementSpeed"], "movement_speed", properties)


def _add_min_max(row: DatRecord, row_key: str, key: str, obj: Dict[str, Dict[str, int]]) -> None:
    if row[row_key] > 0:
        obj[key] = {"min": row[row_key], "max": row[row_key]}


def _convert_shield_properties(shield_row: Optional[DatRecord], properties: Dict[str, Any]) -> None:
    if shield_row is None:
        return
    properties["block"] = shield_row["Block"]


def _convert_flask_properties(flask_row: Optional[DatRecord], properties: Dict[str, Any]) -> None:
    if flask_row is None:
        return
    _add_if_greater_zero(flask_row["LifePerUse"], "life_per_use", properties)
    _add_if_greater_zero(flask_row["ManaPerUse"], "mana_per_use", properties)
    _add_if_greater_zero(flask_row["RecoveryTime"], "duration", properties)


def _convert_flask_buff(flask_row: Optional[DatRecord], item_object: Dict[str, Any]) -> None:
    if flask_row is None or flask_row["BuffDefinitionsKey"] is None:
        return None
    stats_values = zip(flask_row["BuffDefinitionsKey"]["StatsKeys"], flask_row["BuffStatValues"])
    item_object["grants_buff"] = {
        "id": flask_row["BuffDefinitionsKey"]["Id"],
        "stats": {},
    }
    for stat, value in stats_values:
        item_object["grants_buff"]["stats"][stat["Id"]] = value


def _convert_flask_charge_properties(flask_row: Optional[DatRecord], properties: Dict[str, Any]) -> None:
    if flask_row is None:
        return
    properties["charges_max"] = flask_row["MaxCharges"]
    properties["charges_per_use"] = flask_row["PerCharge"]


def _convert_weapon_properties(weapon_row: Optional[DatRecord], properties: Dict[str, Any]) -> None:
    if weapon_row is None:
        return
    properties["critical_strike_chance"] = weapon_row["Critical"]
    properties["attack_time"] = weapon_row["Speed"]
    properties["physical_damage_min"] = weapon_row["DamageMin"]
    properties["physical_damage_max"] = weapon_row["DamageMax"]
    properties["range"] = weapon_row["RangeMax"]


def _convert_currency_properties(currency_row: Optional[DatRecord], properties: Dict[str, Any]) -> None:
    if currency_row is None:
        return
    properties["stack_size"] = currency_row["StackSize"]
    properties["directions"] = currency_row["Directions"]
    if currency_row["FullStack_BaseItemTypesKey"]:
        properties["full_stack_turns_into"] = currency_row["FullStack_BaseItemTypesKey"]["Id"]
    properties["description"] = currency_row["Description"]
    properties["stack_size_currency_tab"] = currency_row["CurrencyTab_StackSize"]


def _create_skills_dict(relational_reader, col="BaseItemType") -> Dict:
    skills_dict = {}
    try:
        for row in relational_reader["ItemInherentSkills.dat64"]:
            if row[col]:
                item_id = row[col]["Id"]
                skills_granted = []
                if row["SkillsGranted"]:
                    for skill in row["SkillsGranted"]:
                        if skill[col]:
                            skills_granted.append(skill[col]["Id"])
                skills_dict[item_id] = skills_granted
    except (KeyError, TypeError):
        print("Warning: ItemInherentSkills.dat64 not found or has incorrect format")

    return defaultdict(lambda: [], skills_dict)  # 默认返回空列表


def _convert_inherent_skills(item_id: str, skills_dict: Dict[str, List[str]], item_object: Dict[str, Any]) -> None:
    skills = skills_dict[item_id]
    if skills:
        item_object["skills_granted"] = skills


class base_items(Parser_Module):
    def write(self) -> None:
        relational_reader = self.relational_reader
        attribute_requirements = _create_default_dict(
            relational_reader["AttributeRequirements.dat64"], col="BaseItemType"
        )
        armour_types = _create_default_dict(relational_reader["ArmourTypes.dat64"])
        shield_types = _create_default_dict(relational_reader["ShieldTypes.dat64"])
        flask_types = _create_default_dict(relational_reader["Flasks.dat64"])
        flask_charges = _create_default_dict(relational_reader["ComponentCharges.dat64"])
        weapon_types = _create_default_dict(relational_reader["WeaponTypes.dat64"])
        currency_type = _create_default_dict(relational_reader["CurrencyItems.dat64"])
        item_skills = _create_skills_dict(relational_reader, col="BaseItemType")
        # Not covered here: SkillGems.dat64 (see gems.py), Essences.dat64 (see essences.py)

        root = {}
        itfiles = {}
        by_class = defaultdict(dict)
        for item in relational_reader["BaseItemTypes.dat64"]:

            it_path = item["InheritsFrom"]
            itfile = self.get_cache(ITFileCache)[it_path + ".it"]
            itfiles[it_path] = itfile
            inherited_tags = list(itfile["Base"]["tag"])
            mod_domain = item["ModDomain"]
            mod_domain = MOD_DOMAIN._value2member_map_.get(mod_domain)
            item_id = item["Id"]
            item_class = item["ItemClass"]["Id"]
            properties: Dict = {}
            _convert_armour_properties(armour_types[item_id], properties)
            _convert_shield_properties(shield_types[item_id], properties)
            _convert_flask_properties(flask_types[item_id], properties)
            _convert_flask_charge_properties(flask_charges[item_id], properties)
            _convert_weapon_properties(weapon_types[item_id], properties)
            _convert_currency_properties(currency_type[item_id], properties)
            visual_identity = item["ItemVisualIdentity"]
            dds_file = visual_identity["DDSFile"]
            result = {
                "name": item["Name"],
                "item_class": item_class,
                "inherits_from": it_path,
                "inventory_width": item["Width"],
                "inventory_height": item["Height"],
                "drop_level": item["DropLevel"],
                "implicits": [mod["Id"] for mod in item["Implicit_ModsKeys"]],
                "tags": [tag["Id"] for tag in item["TagsKeys"]] + inherited_tags,
                "visual_identity": {
                    "id": visual_identity["Id"],
                    "dds_file": dds_file,
                },
                "requirements": _convert_requirements(
                    attribute_requirements[item_id],
                    item["DropLevel"],
                ),
                "properties": properties,
                "release_state": get_release_state(item_id).name,
                "domain": (
                    mod_domain.name.lower()
                    if mod_domain and mod_domain is not MOD_DOMAIN.MODS_DISALLOWED
                    else "undefined"
                ),
            }
            _convert_flask_buff(flask_types[item_id], result)
            _convert_inherent_skills(item_id, item_skills, result)
            root[item_id] = result
            if item_class:
                by_class[item_class][item_id] = result

            if self.language == "English" and dds_file:
                export_image(
                    dds_file,
                    self.data_path,
                    self.file_system,
                    compose=compose_flask if visual_identity["Composition"] == 1 else None,
                )

        write_json(root, self.data_path, "base_items")
        for k, v in by_class.items():
            write_json(v, self.data_path, f"base_items/{k}")
        if self.language == "English":
            for k, v in itfiles.items():
                write_any_json(v, self.data_path, k)


if __name__ == "__main__":
    call_with_default_args(base_items)
