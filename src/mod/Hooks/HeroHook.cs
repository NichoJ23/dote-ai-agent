using System.Collections.Generic;
using System.Reflection;
using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts hero states: HP, room, level, weapon class, skills with unlock levels,
    /// full skill tree, equipment with weapon types, operating/crystal status.
    /// </summary>
    public class HeroHook : IStateHook
    {
        private DungeonHook dungeonHook;
        private FieldInfo gatheringItemField;
        private FieldInfo levelConfigsField;

        public string HookId { get { return "heroes"; } }
        public bool IsBound { get { return dungeonHook != null && dungeonHook.IsBound; } }

        public HeroHook(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
            // Cache reflection fields for private Hero fields
            gatheringItemField = typeof(Hero).GetField("gatheringItem", BindingFlags.NonPublic | BindingFlags.Instance);
            levelConfigsField = typeof(Hero).GetField("levelConfigs", BindingFlags.NonPublic | BindingFlags.Instance);
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

            // Name, faction, and weapon class from HeroConfig
            if (hero.Config != null)
            {
                data.Name = !string.IsNullOrEmpty(hero.LocalizedName)
                    ? hero.LocalizedName
                    : hero.Config.Name.ToString();
                data.Faction = hero.Config.Faction.ToString();
                data.WeaponClass = hero.Config.AttackType;
            }
            else
            {
                data.Name = hero.LocalizedName ?? hero.name;
                data.Faction = "Unknown";
                data.WeaponClass = null;
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
            data.IsUsable = hero.IsUsable;

            // Combat stats from simulation properties
            try
            {
                data.Attack = hero.GetSimPropertyValue(SimulationProperties.AttackPower);
                data.Defense = hero.GetSimPropertyValue(SimulationProperties.Defense);
                data.Speed = hero.GetSimPropertyValue(SimulationProperties.MoveSpeed);
                data.Wit = hero.GetSimPropertyValue(SimulationProperties.Wit);
                data.AttackCooldown = hero.GetSimPropertyValue(SimulationProperties.AttackCooldown);
            }
            catch (System.Exception)
            {
                // Simulation may not be loaded yet for this hero
            }

            // Build the skill tree and unlock level mapping from levelConfigs
            // levelConfigs[i] corresponds to hero level (i+1) and contains Skills[] unlocked at that level
            var skillUnlockLevels = new Dictionary<string, int>();
            data.SkillTree = new List<SkillTreeEntry>();
            List<HeroLevelConfig> levelConfigs = GetLevelConfigs(hero);
            if (levelConfigs != null)
            {
                IDatabase<SkillConfig> skillDb = Databases.GetDatabase<SkillConfig>(false);

                for (int lvl = 0; lvl < levelConfigs.Count; lvl++)
                {
                    HeroLevelConfig levelCfg = levelConfigs[lvl];
                    if (levelCfg == null || levelCfg.Skills == null)
                        continue;

                    int heroLevel = lvl + 1; // levelConfigs[0] = level 1, etc.

                    for (int s = 0; s < levelCfg.Skills.Length; s++)
                    {
                        string skillName = levelCfg.Skills[s];
                        if (string.IsNullOrEmpty(skillName))
                            continue;

                        // Track unlock level for each skill name
                        skillUnlockLevels[skillName] = heroLevel;

                        // Build skill tree entry
                        var entry = new SkillTreeEntry();
                        entry.SkillName = skillName;
                        entry.UnlockHeroLevel = heroLevel;
                        entry.IsUnlocked = hero.Level >= heroLevel;

                        // Try to get details from SkillConfig database
                        if (skillDb != null)
                        {
                            SkillConfig skillCfg = skillDb.GetValue(skillName);
                            if (skillCfg != null)
                            {
                                skillCfg.Init();
                                entry.BaseName = skillCfg.BaseName;
                                entry.IsActive = skillCfg.IsActive;
                                entry.SkillLevel = skillCfg.Level;
                            }
                            else
                            {
                                // Infer from naming convention
                                entry.IsActive = skillName.StartsWith("Skill_A");
                                entry.BaseName = skillName;
                                entry.SkillLevel = 1;
                            }
                        }
                        else
                        {
                            entry.IsActive = skillName.StartsWith("Skill_A");
                            entry.BaseName = skillName;
                            entry.SkillLevel = 1;
                        }

                        data.SkillTree.Add(entry);
                    }
                }
            }

            // Active skills (currently unlocked, filtered to highest level per base name)
            data.ActiveSkills = new List<ActiveSkillData>();
            List<ActiveSkill> actives = hero.FilteredActiveSkills;
            if (actives != null)
            {
                for (int i = 0; i < actives.Count; i++)
                {
                    ActiveSkill skill = actives[i];
                    if (skill == null || skill.Config == null)
                        continue;

                    skill.Config.Init();
                    var skillData = new ActiveSkillData();
                    skillData.Name = skill.Config.Name.ToString();
                    skillData.SkillLevel = skill.Config.Level;
                    skillData.CooldownTurns = skill.Config.CooldownTurnsCount;
                    skillData.RemainingCooldown = skill.GetRemainingTurns();
                    skillData.IsActivated = skill.IsActivated;

                    // Look up unlock level from our skill tree map
                    int unlockLvl;
                    if (skillUnlockLevels.TryGetValue(skill.Config.Name.ToString(), out unlockLvl))
                        skillData.UnlockLevel = unlockLvl;
                    else
                        skillData.UnlockLevel = 0; // Present from start or unknown

                    data.ActiveSkills.Add(skillData);
                }
            }

            // Passive skills (currently unlocked, filtered to highest level per base name)
            data.PassiveSkills = new List<PassiveSkillData>();
            List<PassiveSkill> passives = hero.FilteredPassiveSkills;
            if (passives != null)
            {
                for (int i = 0; i < passives.Count; i++)
                {
                    PassiveSkill skill = passives[i];
                    if (skill == null || skill.Config == null)
                        continue;

                    skill.Config.Init();
                    var skillData = new PassiveSkillData();
                    skillData.Name = skill.Config.Name.ToString();
                    skillData.SkillLevel = skill.Config.Level;

                    // Look up unlock level from our skill tree map
                    int unlockLvl;
                    if (skillUnlockLevels.TryGetValue(skill.Config.Name.ToString(), out unlockLvl))
                        skillData.UnlockLevel = unlockLvl;
                    else
                        skillData.UnlockLevel = 0; // Present from start or unknown

                    data.PassiveSkills.Add(skillData);
                }
            }

            // Equipment (with weapon type and attack type for weapon items)
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

                    if (slot.EquippedItem != null)
                    {
                        slotData.ItemName = slot.EquippedItem.Name.ToString();

                        // Extract weapon type and attack type from the item's config
                        ItemHeroConfig itemCfg = slot.EquippedItem.ItemConfig;
                        if (itemCfg != null)
                        {
                            if (itemCfg.CategoryParameters != null && itemCfg.CategoryParameters.TypeName != null)
                            {
                                slotData.WeaponType = itemCfg.CategoryParameters.TypeName.ToString();
                            }
                            if (itemCfg.AttackTypeConfigName != null)
                            {
                                slotData.AttackType = itemCfg.AttackTypeConfigName.ToString();
                            }
                        }
                    }

                    data.Equipment.Add(slotData);
                }
            }

            return data;
        }

        /// <summary>
        /// Gets the hero's level configs via reflection (private field).
        /// Returns null if not accessible.
        /// </summary>
        private List<HeroLevelConfig> GetLevelConfigs(Hero hero)
        {
            if (levelConfigsField == null)
                return null;
            try
            {
                return levelConfigsField.GetValue(hero) as List<HeroLevelConfig>;
            }
            catch (System.Exception)
            {
                return null;
            }
        }
    }
}
