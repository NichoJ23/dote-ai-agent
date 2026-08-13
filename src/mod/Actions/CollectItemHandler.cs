using System.Collections.Generic;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles COLLECT_ITEM command: moves a hero to the room containing a dropped item.
    /// Items are auto-collected when a hero is in the room, so this is effectively
    /// a MOVE_HERO with validation that the item exists.
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to send
    ///   room_index (int, required) - Room where the item is located
    /// </summary>
    public class CollectItemHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "COLLECT_ITEM"; } }

        public CollectItemHandler(DungeonHook dungeonHook)
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

            Hero hero = FindHeroByName(heroName);
            if (hero == null)
                return "Hero not found: " + heroName;

            if (!hero.IsUsable)
                return "Hero is not usable: " + heroName;

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

            // Move hero to room — items are auto-collected on arrival
            // MoveToRoom(Room destination, bool immediate, bool cancelOperating, bool cancelInteracting)
            hero.MoveToRoom(targetRoom, false, true, true);

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["room_index"] = roomIndex;

            return ActionResult.Ok(metadata);
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
