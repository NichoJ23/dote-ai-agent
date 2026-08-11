using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles MOVE_HERO command: moves a hero to a target room.
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to move
    ///   target_room_index (int, required) - Index of the destination room
    /// </summary>
    public class MoveHeroHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "MOVE_HERO"; } }

        public MoveHeroHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            if (string.IsNullOrEmpty(heroName))
                return "Missing required parameter: hero_name";

            int targetRoomIndex = command.GetInt("target_room_index", -1);
            if (targetRoomIndex < 0)
                return "Missing or invalid parameter: target_room_index";

            // Find hero
            Hero hero = FindHeroByName(heroName);
            if (hero == null)
                return "Hero not found: " + heroName;

            // Check hero is usable
            if (!hero.IsUsable)
                return "Hero is not usable (may be dead, interacting, or respawning): " + heroName;

            // Find target room
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null || dungeon.OpenedRooms == null)
                return "Dungeon not available";

            List<Room> rooms = dungeon.OpenedRooms;
            if (targetRoomIndex >= rooms.Count)
                return "Invalid target_room_index: " + targetRoomIndex + " (only " + rooms.Count + " rooms opened)";

            Room targetRoom = rooms[targetRoomIndex];
            if (targetRoom == null)
                return "Target room is null at index " + targetRoomIndex;

            return null; // All good
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            int targetRoomIndex = command.GetInt("target_room_index", -1);

            Hero hero = FindHeroByName(heroName);
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            Room targetRoom = dungeon.OpenedRooms[targetRoomIndex];

            // Get current room for metadata
            Room currentRoom = hero.RoomElement.ParentRoom;
            int currentRoomIndex = dungeonHook.GetRoomIndex(currentRoom);

            // Move hero to room
            // MoveToRoom(Room destination, bool immediate, bool cancelOperating, bool cancelInteracting)
            hero.MoveToRoom(targetRoom, false, true, true);

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["from_room_index"] = currentRoomIndex;
            metadata["to_room_index"] = targetRoomIndex;

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
