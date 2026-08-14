using System.Collections.Generic;
using System.Reflection;
using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts recruitable (not yet recruited) heroes found in rooms.
    /// Includes weapon class, active skills, passive skills, and full skill tree.
    /// </summary>
    public class RecruitHook : IStateHook
    {
        private DungeonHook dungeonHook;
        private Dungeon dungeon;
        private FieldInfo levelConfigsField;

        public string HookId { get { return "recruits"; } }
        public bool IsBound { get { return dungeonHook != null && dungeonHook.IsBound; } }

        public RecruitHook(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
            levelConfigsField = typeof(Hero).GetField("levelConfigs", BindingFlags.NonPublic | BindingFlags.Instance);
        }

        public bool TryBind()
        {
            dungeon = SingletonManager.Get<Dungeon>(false);
            return dungeonHook != null && dungeonHook.IsBound && dungeon != null;
        }

        public object ExtractState()
        {
            if (dungeon == null)
                dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return new List<RecruitableHeroData>();

            var result = new List<RecruitableHeroData>();
            List<Room> rooms = dungeon.OpenedRooms;
            if (rooms == null)
                return result;

            for (int r = 0; r < rooms.Count; r++)
            {
                Room room = rooms[r];
                if (room == null || room.Heroes == null)
                    continue;

                for (int h = 0; h < room.Heroes.Count; h++)
                {
                    Hero hero = room.Heroes[h];
                    if (hero == null)
                        continue;
                    if (!hero.IsRecruitable || hero.IsRecruited)
                        continue;

                    var data = new RecruitableHeroData();
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

                    data.RoomIndex = dungeonHook.GetRoomIndex(room);

                    if (hero.HealthCpnt != null)
                    {
                        data.Hp = hero.HealthCpnt.GetHealth();
                        data.MaxHp = hero.HealthCpnt.GetMaxHealth();
                    }

                    // Recruit cost
                    try
                    {
                        data.RecruitCostFood = hero.GetHiringFoodCost();
                    }
                    catch (System.Exception)
                    {
                        data.RecruitCostFood = 0f;
                    }

                    // Active skills (currently on the hero)
                    data.ActiveSkillNames = new List<string>();
                    if (hero.FilteredActiveSkills != null)
                    {
                        for (int i = 0; i < hero.FilteredActiveSkills.Count; i++)
                        {
                            ActiveSkill skill = hero.FilteredActiveSkills[i];
                            if (skill != null && skill.Config != null)
                                data.ActiveSkillNames.Add(skill.Config.Name.ToString());
                        }
                    }

                    // Passive skills (currently on the hero)
                    data.PassiveSkillNames = new List<string>();
                    if (hero.FilteredPassiveSkills != null)
                    {
                        for (int i = 0; i < hero.FilteredPassiveSkills.Count; i++)
                        {
                            PassiveSkill skill = hero.FilteredPassiveSkills[i];
                            if (skill != null && skill.Config != null)
                                data.PassiveSkillNames.Add(skill.Config.Name.ToString());
                        }
                    }

                    // Full skill tree from levelConfigs
                    data.SkillTree = BuildSkillTree(hero);

                    result.Add(data);
                }
            }

            return result;
        }

        /// <summary>
        /// Builds the complete skill tree for a hero by reading its levelConfigs.
        /// This shows all abilities that will unlock at each level, helping the agent
        /// evaluate a recruit's long-term value.
        /// </summary>
        private List<SkillTreeEntry> BuildSkillTree(Hero hero)
        {
            var tree = new List<SkillTreeEntry>();

            List<HeroLevelConfig> levelConfigs = GetLevelConfigs(hero);
            if (levelConfigs == null)
                return tree;

            IDatabase<SkillConfig> skillDb = Databases.GetDatabase<SkillConfig>(false);

            for (int lvl = 0; lvl < levelConfigs.Count; lvl++)
            {
                HeroLevelConfig levelCfg = levelConfigs[lvl];
                if (levelCfg == null || levelCfg.Skills == null)
                    continue;

                int heroLevel = lvl + 1;

                for (int s = 0; s < levelCfg.Skills.Length; s++)
                {
                    string skillName = levelCfg.Skills[s];
                    if (string.IsNullOrEmpty(skillName))
                        continue;

                    var entry = new SkillTreeEntry();
                    entry.SkillName = skillName;
                    entry.UnlockHeroLevel = heroLevel;
                    entry.IsUnlocked = hero.Level >= heroLevel;

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

                    tree.Add(entry);
                }
            }

            return tree;
        }

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
