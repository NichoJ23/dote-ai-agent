using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts recruitable (not yet recruited) heroes found in rooms.
    /// </summary>
    public class RecruitHook : IStateHook
    {
        private DungeonHook dungeonHook;
        private Dungeon dungeon;

        public string HookId { get { return "recruits"; } }
        public bool IsBound { get { return dungeonHook != null && dungeonHook.IsBound; } }

        public RecruitHook(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
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
                    }
                    else
                    {
                        data.Name = hero.LocalizedName ?? hero.name;
                        data.Faction = "Unknown";
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

                    // Passive skills
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

                    result.Add(data);
                }
            }

            return result;
        }
    }
}
