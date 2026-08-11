using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles RECRUIT_HERO command: recruits a hero found in a room.
    /// The recruiter hero must be in the same room as the recruitable hero.
    /// Food cost is handled internally by the game.
    /// 
    /// Parameters:
    ///   recruiter_hero_name (string, required) - Name of the hero performing recruitment
    ///   recruit_name (string, required) - Name of the hero to recruit
    /// </summary>
    public class RecruitHeroHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "RECRUIT_HERO"; } }

        public RecruitHeroHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string recruiterName = command.GetString("recruiter_hero_name");
            if (string.IsNullOrEmpty(recruiterName))
                return "Missing required parameter: recruiter_hero_name";

            string recruitName = command.GetString("recruit_name");
            if (string.IsNullOrEmpty(recruitName))
                return "Missing required parameter: recruit_name";

            // Find recruiter
            Hero recruiter = FindRecruitedHeroByName(recruiterName);
            if (recruiter == null)
                return "Recruiter hero not found: " + recruiterName;

            if (!recruiter.IsUsable)
                return "Recruiter hero is not usable: " + recruiterName;

            if (recruiter.HasCrystal)
                return "Cannot recruit while carrying the crystal";

            // Find the recruit
            Hero recruit = FindRecruitableHeroByName(recruitName);
            if (recruit == null)
                return "Recruitable hero not found: " + recruitName;

            if (recruit.IsRecruited)
                return "Hero is already recruited: " + recruitName;

            if (!recruit.IsRecruitable)
                return "Hero is not recruitable: " + recruitName;

            // Validate same room
            Room recruiterRoom = recruiter.RoomElement.ParentRoom;
            Room recruitRoom = recruit.RoomElement.ParentRoom;

            if (recruiterRoom != recruitRoom)
            {
                int recruiterRoomIndex = dungeonHook.GetRoomIndex(recruiterRoom);
                int recruitRoomIndex = dungeonHook.GetRoomIndex(recruitRoom);
                return "Recruiter " + recruiterName + " (room " + recruiterRoomIndex
                    + ") is not in the same room as recruit " + recruitName
                    + " (room " + recruitRoomIndex + ")";
            }

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string recruitName = command.GetString("recruit_name");

            Hero recruit = FindRecruitableHeroByName(recruitName);

            // Recruit(bool consumeFood, bool registerRecruitment, bool requestAccessToServer)
            recruit.Recruit(true, true, true);

            var metadata = new Dictionary<string, object>();
            metadata["recruit_name"] = recruitName;
            metadata["recruiter_hero_name"] = command.GetString("recruiter_hero_name");

            return ActionResult.Ok(metadata);
        }

        /// <summary>Finds a recruited (player-controlled) hero by name.</summary>
        private Hero FindRecruitedHeroByName(string name)
        {
            List<Hero> heroes = Hero.LocalPlayerActiveRecruitedHeroes;
            if (heroes == null)
                return null;

            for (int i = 0; i < heroes.Count; i++)
            {
                Hero hero = heroes[i];
                if (hero == null)
                    continue;

                string heroName = hero.LocalizedName;
                if (string.IsNullOrEmpty(heroName) && hero.Config != null)
                    heroName = hero.Config.Name.ToString();

                if (heroName == name)
                    return hero;
            }
            return null;
        }

        /// <summary>Finds a recruitable (not yet recruited) hero by name across all rooms.</summary>
        private Hero FindRecruitableHeroByName(string name)
        {
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null || dungeon.OpenedRooms == null)
                return null;

            List<Room> rooms = dungeon.OpenedRooms;
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

                    string heroName = hero.LocalizedName;
                    if (string.IsNullOrEmpty(heroName) && hero.Config != null)
                        heroName = hero.Config.Name.ToString();

                    if (heroName == name)
                        return hero;
                }
            }
            return null;
        }
    }
}
