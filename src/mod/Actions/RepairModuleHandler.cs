using System.Collections.Generic;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles REPAIR_MODULE command: moves a repair-capable hero to a room with damaged modules.
    /// Repair happens automatically when the hero with the Repair passive enters the room.
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero with Repair passive
    ///   room_index (int, required) - Room with damaged modules to repair
    /// </summary>
    public class RepairModuleHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "REPAIR_MODULE"; } }

        public RepairModuleHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            if (string.IsNullOrEmpty(heroName))
                return "Missing required parameter: hero_name";

            int roomIndex = command.GetInt("room_index", -1);
            if (roomIndex < 0)
                return "Missing or invalid parameter: room_index";

            // Find hero
            Hero hero = FindHeroByName(heroName);
            if (hero == null)
                return "Hero not found: " + heroName;

            if (!hero.IsUsable)
                return "Hero is not usable: " + heroName;

            // Check hero has Repair passive
            if (!HeroHasRepairSkill(hero))
                return "Hero " + heroName + " does not have the Repair passive skill";

            // Validate room
            Room targetRoom = dungeonHook.GetRoomByOpeningIndex(roomIndex);
            if (targetRoom == null)
                return "Invalid room_index: " + roomIndex + " (room not found)";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            int roomIndex = command.GetInt("room_index", -1);

            Hero hero = FindHeroByName(heroName);
            Room targetRoom = dungeonHook.GetRoomByOpeningIndex(roomIndex);

            // Move hero to the room — repair starts automatically via HeroAI
            // MoveToRoom(Room destination, bool immediate, bool cancelOperating, bool cancelInteracting)
            hero.MoveToRoom(targetRoom, false, true, true);

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["room_index"] = roomIndex;

            return ActionResult.Ok(metadata);
        }

        private bool HeroHasRepairSkill(Hero hero)
        {
            List<PassiveSkill> passives = hero.FilteredPassiveSkills;
            if (passives == null)
                return false;

            for (int i = 0; i < passives.Count; i++)
            {
                PassiveSkill skill = passives[i];
                if (skill == null || skill.Config == null)
                    continue;

                string skillName = skill.Config.Name.ToString();
                // The Repair passive can have different names depending on localization
                // but the config name should contain "Repair"
                if (skillName.Contains("Repair"))
                    return true;
            }
            return false;
        }

        private Hero FindHeroByName(string name)
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
    }
}
