using System.Collections.Generic;
using System.Reflection;
using DotEAgent.Models;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts hero states: HP, room, level, skills, equipment, operating/crystal status.
    /// </summary>
    public class HeroHook : IStateHook
    {
        private DungeonHook dungeonHook;
        private FieldInfo gatheringItemField;

        public string HookId { get { return "heroes"; } }
        public bool IsBound { get { return dungeonHook != null && dungeonHook.IsBound; } }

        public HeroHook(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
            // Cache reflection field for gatheringItem (private field on Hero)
            gatheringItemField = typeof(Hero).GetField("gatheringItem", BindingFlags.NonPublic | BindingFlags.Instance);
        }

        public bool TryBind()
        {
            // HeroHook depends on DungeonHook being bound (for room index lookup)
            return dungeonHook != null && dungeonHook.IsBound;
        }

        public object ExtractState()
        {
            List<Hero> heroes = Hero.LocalPlayerActiveRecruitedHeroes;
            if (heroes == null || heroes.Count == 0)
                return null;

            var result = new List<HeroStateData>(heroes.Count);
            for (int i = 0; i < heroes.Count; i++)
            {
                Hero hero = heroes[i];
                if (hero == null)
                    continue;
                result.Add(ExtractHero(hero));
            }

            return result;
        }

        private HeroStateData ExtractHero(Hero hero)
        {
            var data = new HeroStateData();

            // Name and faction from HeroConfig
            if (hero.Config != null)
            {
                data.Name = !string.IsNullOrEmpty(hero.LocalizedName)
                    ? hero.LocalizedName
                    : hero.Config.Name.ToString();
                data.Faction = hero.Config.Faction.ToString();
            }
            else
            {
                data.Name = hero.LocalizedName ?? hero.name;
                data.Faction = "Unknown";
            }

            // Room
            if (hero.RoomElement != null && hero.RoomElement.ParentRoom != null)
            {
                data.RoomIndex = dungeonHook.GetRoomIndex(hero.RoomElement.ParentRoom);
            }
            else
            {
                data.RoomIndex = -1;
            }

            // Health
            if (hero.HealthCpnt != null)
            {
                data.Hp = hero.HealthCpnt.GetHealth();
                data.MaxHp = hero.HealthCpnt.GetMaxHealth();
            }

            // Level
            data.Level = hero.Level;

            // Crystal and operating state
            data.HasCrystal = hero.HasCrystal;
            data.IsOperating = hero.OperatingModule != null;
            if (data.IsOperating)
            {
                data.OperatingModuleName = hero.OperatingModule.name;
            }

            // Item gathering state (hero is mid-pickup animation — moving cancels it!)
            if (gatheringItemField != null)
            {
                data.IsGatheringItem = gatheringItemField.GetValue(hero) != null;
            }

            data.IsRecruitable = hero.IsRecruitable;
            data.IsRecruited = hero.IsRecruited;

            // Active skills
            data.ActiveSkills = new List<ActiveSkillData>();
            List<ActiveSkill> actives = hero.FilteredActiveSkills;
            if (actives != null)
            {
                for (int i = 0; i < actives.Count; i++)
                {
                    ActiveSkill skill = actives[i];
                    if (skill == null)
                        continue;

                    var skillData = new ActiveSkillData();
                    skillData.Name = skill.Config != null ? skill.Config.Name.ToString() : "Unknown";
                    skillData.CooldownTurns = skill.Config != null ? skill.Config.CooldownTurnsCount : 0;
                    skillData.RemainingCooldown = skill.GetRemainingTurns();
                    skillData.IsActivated = skill.IsActivated;
                    data.ActiveSkills.Add(skillData);
                }
            }

            // Passive skills
            data.PassiveSkills = new List<PassiveSkillData>();
            List<PassiveSkill> passives = hero.FilteredPassiveSkills;
            if (passives != null)
            {
                for (int i = 0; i < passives.Count; i++)
                {
                    PassiveSkill skill = passives[i];
                    if (skill == null)
                        continue;

                    var skillData = new PassiveSkillData();
                    skillData.Name = skill.Config != null ? skill.Config.Name.ToString() : "Unknown";
                    data.PassiveSkills.Add(skillData);
                }
            }

            // Equipment
            data.Equipment = new List<EquipmentSlotData>();
            EquipmentSlot[] slots = hero.EquipmentSlots;
            if (slots != null)
            {
                for (int i = 0; i < slots.Length; i++)
                {
                    EquipmentSlot slot = slots[i];
                    if (slot == null)
                        continue;

                    var slotData = new EquipmentSlotData();
                    slotData.SlotCategory = slot.CategoryParameters != null
                        ? slot.CategoryParameters.CategoryName.ToString()
                        : "Unknown";
                    slotData.ItemName = slot.EquippedItem != null
                        ? slot.EquippedItem.Name.ToString()
                        : null;
                    data.Equipment.Add(slotData);
                }
            }

            return data;
        }
    }
}
