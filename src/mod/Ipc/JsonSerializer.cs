using System.Collections.Generic;
using System.Globalization;
using System.Text;
using DotEAgent.Models;

namespace DotEAgent.Ipc
{
    /// <summary>
    /// Manual .NET 3.5-compatible JSON serializer for GameStatePayload.
    /// Produces snake_case JSON matching the Python-side schema.
    /// No external dependencies - pure StringBuilder-based output.
    /// </summary>
    public static class JsonSerializer
    {
        public static string Serialize(GameStatePayload state)
        {
            StringBuilder sb = new StringBuilder(8192);
            sb.Append("{");
            AppendInt(sb, "turn", state.Turn, true);
            AppendInt(sb, "floor", state.Floor, false);
            AppendString(sb, "game_phase", state.GamePhase, false);
            AppendString(sb, "crystal_state", state.CrystalState, false);
            AppendInt(sb, "exit_room_index", state.ExitRoomIndex, false);
            AppendInt(sb, "start_room_index", state.StartRoomIndex, false);
            AppendFloat(sb, "time_scale", state.TimeScale, false);

            // Resources
            sb.Append(",\"resources\":");
            SerializeResources(sb, state.Resources);

            // Rooms
            sb.Append(",\"rooms\":");
            SerializeRoomList(sb, state.Rooms);

            // Closed doors
            sb.Append(",\"closed_doors\":");
            SerializeDoorList(sb, state.ClosedDoors);

            // Heroes
            sb.Append(",\"heroes\":");
            SerializeHeroList(sb, state.Heroes);

            // Mobs
            sb.Append(",\"mobs\":");
            SerializeMobList(sb, state.Mobs);

            // Merchants
            sb.Append(",\"merchants\":");
            SerializeMerchantList(sb, state.Merchants);

            // Recruitable heroes
            sb.Append(",\"recruitable_heroes\":");
            SerializeRecruitList(sb, state.RecruitableHeroes);

            // Dropped items
            sb.Append(",\"dropped_items\":");
            SerializeDroppedItemList(sb, state.DroppedItems);

            // Backpack items
            sb.Append(",\"backpack_items\":");
            SerializeBackpackItemList(sb, state.BackpackItems);

            // Shared inventory items
            sb.Append(",\"shared_inventory_items\":");
            SerializeBackpackItemList(sb, state.SharedInventoryItems);

            // Researchable blueprints
            sb.Append(",\"researchable_blueprints\":");
            SerializeResearchBlueprintList(sb, state.ResearchableBlueprints);

            sb.Append("}");
            return sb.ToString();
        }

        // --- Resources ---

        private static void SerializeResources(StringBuilder sb, ResourceStateData r)
        {
            if (r == null)
            {
                sb.Append("null");
                return;
            }
            sb.Append("{");
            AppendFloat(sb, "industry", r.Industry, true);
            AppendFloat(sb, "food", r.Food, false);
            AppendFloat(sb, "science", r.Science, false);
            AppendFloat(sb, "dust", r.Dust, false);
            AppendFloat(sb, "dust_max", r.DustMax, false);
            AppendFloat(sb, "industry_per_turn", r.IndustryPerTurn, false);
            AppendFloat(sb, "food_per_turn", r.FoodPerTurn, false);
            AppendFloat(sb, "science_per_turn", r.SciencePerTurn, false);
            AppendFloat(sb, "dust_per_turn", r.DustPerTurn, false);
            AppendFloat(sb, "room_power_cost", r.RoomPowerCost, false);
            AppendInt(sb, "powered_room_count", r.PoweredRoomCount, false);
            sb.Append("}");
        }

        // --- Rooms ---

        private static void SerializeRoomList(StringBuilder sb, List<RoomStateData> rooms)
        {
            if (rooms == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < rooms.Count; i++)
            {
                if (i > 0) sb.Append(",");
                SerializeRoom(sb, rooms[i]);
            }
            sb.Append("]");
        }

        private static void SerializeRoom(StringBuilder sb, RoomStateData r)
        {
            sb.Append("{");
            AppendInt(sb, "index", r.Index, true);
            AppendBool(sb, "is_powered", r.IsPowered, false);
            AppendBool(sb, "is_auto_powered", r.IsAutoPowered, false);
            AppendBool(sb, "is_exit_room", r.IsExitRoom, false);
            AppendBool(sb, "is_start_room", r.IsStartRoom, false);
            AppendBool(sb, "is_fully_opened", r.IsFullyOpened, false);
            AppendInt(sb, "depth", r.Depth, false);
            AppendBool(sb, "suffers_emp", r.SuffersEMP, false);
            AppendInt(sb, "emp_turns_remaining", r.EmpTurnsRemaining, false);
            AppendInt(sb, "dust_loot_amount", r.DustLootAmount, false);
            AppendBool(sb, "has_artifact", r.HasArtifact, false);
            AppendBool(sb, "has_stele", r.HasStele, false);

            // Adjacent rooms
            sb.Append(",\"adjacent_room_indices\":");
            SerializeIntList(sb, r.AdjacentRoomIndices);

            AppendStringOrNull(sb, "major_module_name", r.MajorModuleName, false);

            // Minor modules
            sb.Append(",\"minor_module_names\":");
            SerializeStringList(sb, r.MinorModuleNames);

            AppendInt(sb, "minor_slot_count", r.MinorSlotCount, false);
            AppendInt(sb, "hero_count", r.HeroCount, false);
            AppendInt(sb, "mob_count", r.MobCount, false);
            AppendInt(sb, "npc_count", r.NpcCount, false);
            sb.Append("}");
        }

        // --- Doors ---

        private static void SerializeDoorList(StringBuilder sb, List<DoorStateData> doors)
        {
            if (doors == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < doors.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("{");
                AppendInt(sb, "room1_index", doors[i].Room1Index, true);
                AppendInt(sb, "room2_index", doors[i].Room2Index, false);
                AppendBool(sb, "is_opening", doors[i].IsOpening, false);
                sb.Append("}");
            }
            sb.Append("]");
        }

        // --- Heroes ---

        private static void SerializeHeroList(StringBuilder sb, List<HeroStateData> heroes)
        {
            if (heroes == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < heroes.Count; i++)
            {
                if (i > 0) sb.Append(",");
                SerializeHero(sb, heroes[i]);
            }
            sb.Append("]");
        }

        private static void SerializeHero(StringBuilder sb, HeroStateData h)
        {
            sb.Append("{");
            AppendString(sb, "name", h.Name, true);
            AppendString(sb, "faction", h.Faction, false);
            AppendInt(sb, "room_index", h.RoomIndex, false);
            AppendFloat(sb, "hp", h.Hp, false);
            AppendFloat(sb, "max_hp", h.MaxHp, false);
            AppendInt(sb, "level", h.Level, false);
            AppendBool(sb, "has_crystal", h.HasCrystal, false);
            AppendBool(sb, "is_operating", h.IsOperating, false);
            AppendStringOrNull(sb, "operating_module_name", h.OperatingModuleName, false);
            AppendBool(sb, "is_gathering_item", h.IsGatheringItem, false);
            AppendBool(sb, "is_recruitable", h.IsRecruitable, false);
            AppendBool(sb, "is_recruited", h.IsRecruited, false);

            // Active skills
            sb.Append(",\"active_skills\":");
            SerializeActiveSkillList(sb, h.ActiveSkills);

            // Passive skills
            sb.Append(",\"passive_skills\":");
            SerializePassiveSkillList(sb, h.PassiveSkills);

            // Equipment
            sb.Append(",\"equipment\":");
            SerializeEquipmentList(sb, h.Equipment);

            sb.Append("}");
        }

        private static void SerializeActiveSkillList(StringBuilder sb, List<ActiveSkillData> skills)
        {
            if (skills == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < skills.Count; i++)
            {
                if (i > 0) sb.Append(",");
                ActiveSkillData s = skills[i];
                sb.Append("{");
                AppendString(sb, "name", s.Name, true);
                AppendInt(sb, "cooldown_turns", s.CooldownTurns, false);
                AppendInt(sb, "remaining_cooldown", s.RemainingCooldown, false);
                AppendBool(sb, "is_activated", s.IsActivated, false);
                sb.Append("}");
            }
            sb.Append("]");
        }

        private static void SerializePassiveSkillList(StringBuilder sb, List<PassiveSkillData> skills)
        {
            if (skills == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < skills.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("{");
                AppendString(sb, "name", skills[i].Name, true);
                sb.Append("}");
            }
            sb.Append("]");
        }

        private static void SerializeEquipmentList(StringBuilder sb, List<EquipmentSlotData> equip)
        {
            if (equip == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < equip.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("{");
                AppendString(sb, "slot_category", equip[i].SlotCategory, true);
                AppendStringOrNull(sb, "item_name", equip[i].ItemName, false);
                sb.Append("}");
            }
            sb.Append("]");
        }

        // --- Mobs ---

        private static void SerializeMobList(StringBuilder sb, List<MobStateData> mobs)
        {
            if (mobs == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < mobs.Count; i++)
            {
                if (i > 0) sb.Append(",");
                MobStateData m = mobs[i];
                sb.Append("{");
                AppendString(sb, "type", m.Type, true);
                AppendInt(sb, "room_index", m.RoomIndex, false);
                AppendFloat(sb, "hp", m.Hp, false);
                AppendFloat(sb, "max_hp", m.MaxHp, false);
                AppendString(sb, "target_type", m.TargetType, false);
                sb.Append("}");
            }
            sb.Append("]");
        }

        // --- Merchants ---

        private static void SerializeMerchantList(StringBuilder sb, List<MerchantStateData> merchants)
        {
            if (merchants == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < merchants.Count; i++)
            {
                if (i > 0) sb.Append(",");
                MerchantStateData m = merchants[i];
                sb.Append("{");
                AppendInt(sb, "room_index", m.RoomIndex, true);
                AppendString(sb, "currency_type", m.CurrencyType, false);

                sb.Append(",\"items\":");
                SerializeMerchantItemList(sb, m.Items);

                sb.Append("}");
            }
            sb.Append("]");
        }

        private static void SerializeMerchantItemList(StringBuilder sb, List<MerchantItemData> items)
        {
            if (items == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < items.Count; i++)
            {
                if (i > 0) sb.Append(",");
                MerchantItemData it = items[i];
                sb.Append("{");
                AppendString(sb, "name", it.Name, true);
                AppendString(sb, "rarity", it.Rarity, false);
                AppendFloat(sb, "cost", it.Cost, false);
                sb.Append("}");
            }
            sb.Append("]");
        }

        // --- Recruitable Heroes ---

        private static void SerializeRecruitList(StringBuilder sb, List<RecruitableHeroData> recruits)
        {
            if (recruits == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < recruits.Count; i++)
            {
                if (i > 0) sb.Append(",");
                RecruitableHeroData r = recruits[i];
                sb.Append("{");
                AppendString(sb, "name", r.Name, true);
                AppendString(sb, "faction", r.Faction, false);
                AppendInt(sb, "room_index", r.RoomIndex, false);
                AppendFloat(sb, "hp", r.Hp, false);
                AppendFloat(sb, "max_hp", r.MaxHp, false);
                AppendFloat(sb, "recruit_cost_food", r.RecruitCostFood, false);

                sb.Append(",\"passive_skill_names\":");
                SerializeStringList(sb, r.PassiveSkillNames);

                sb.Append("}");
            }
            sb.Append("]");
        }

        // --- Dropped Items ---

        private static void SerializeDroppedItemList(StringBuilder sb, List<DroppedItemData> items)
        {
            if (items == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < items.Count; i++)
            {
                if (i > 0) sb.Append(",");
                DroppedItemData it = items[i];
                sb.Append("{");
                AppendString(sb, "type", it.Type, true);
                AppendStringOrNull(sb, "name", it.Name, false);
                AppendInt(sb, "room_index", it.RoomIndex, false);
                AppendFloat(sb, "dust_amount", it.DustAmount, false);
                sb.Append("}");
            }
            sb.Append("]");
        }

        // --- Backpack / Shared Inventory Items ---

        private static void SerializeBackpackItemList(StringBuilder sb, List<BackpackItemData> items)
        {
            if (items == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < items.Count; i++)
            {
                if (i > 0) sb.Append(",");
                BackpackItemData it = items[i];
                sb.Append("{");
                AppendString(sb, "name", it.Name, true);
                AppendString(sb, "rarity", it.Rarity, false);
                AppendString(sb, "category", it.Category, false);
                sb.Append("}");
            }
            sb.Append("]");
        }

        // --- Utility list serializers ---

        private static void SerializeIntList(StringBuilder sb, List<int> list)
        {
            if (list == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < list.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append(list[i]);
            }
            sb.Append("]");
        }

        private static void SerializeStringList(StringBuilder sb, List<string> list)
        {
            if (list == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < list.Count; i++)
            {
                if (i > 0) sb.Append(",");
                AppendJsonString(sb, list[i]);
            }
            sb.Append("]");
        }

        private static void SerializeResearchBlueprintList(StringBuilder sb, List<ResearchBlueprintData> list)
        {
            if (list == null)
            {
                sb.Append("[]");
                return;
            }
            sb.Append("[");
            for (int i = 0; i < list.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("{\"name\":");
                AppendJsonString(sb, list[i].Name);
                sb.Append(",\"science_cost\":");
                sb.Append(list[i].ScienceCost.ToString("G"));
                sb.Append("}");
            }
            sb.Append("]");
        }

        // --- Primitive append helpers ---

        private static void AppendInt(StringBuilder sb, string key, int value, bool first)
        {
            if (!first) sb.Append(",");
            sb.Append("\"");
            sb.Append(key);
            sb.Append("\":");
            sb.Append(value);
        }

        private static void AppendFloat(StringBuilder sb, string key, float value, bool first)
        {
            if (!first) sb.Append(",");
            sb.Append("\"");
            sb.Append(key);
            sb.Append("\":");
            sb.Append(value.ToString(CultureInfo.InvariantCulture));
        }

        private static void AppendBool(StringBuilder sb, string key, bool value, bool first)
        {
            if (!first) sb.Append(",");
            sb.Append("\"");
            sb.Append(key);
            sb.Append("\":");
            sb.Append(value ? "true" : "false");
        }

        private static void AppendString(StringBuilder sb, string key, string value, bool first)
        {
            if (!first) sb.Append(",");
            sb.Append("\"");
            sb.Append(key);
            sb.Append("\":");
            AppendJsonString(sb, value);
        }

        private static void AppendStringOrNull(StringBuilder sb, string key, string value, bool first)
        {
            if (!first) sb.Append(",");
            sb.Append("\"");
            sb.Append(key);
            sb.Append("\":");
            if (value == null)
                sb.Append("null");
            else
                AppendJsonString(sb, value);
        }

        /// <summary>Appends a JSON-escaped string value (with surrounding quotes).</summary>
        private static void AppendJsonString(StringBuilder sb, string value)
        {
            if (value == null)
            {
                sb.Append("null");
                return;
            }
            sb.Append("\"");
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default: sb.Append(c); break;
                }
            }
            sb.Append("\"");
        }
    }
}
