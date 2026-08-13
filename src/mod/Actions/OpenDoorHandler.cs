using System.Collections.Generic;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles OPEN_DOOR command: opens a closed door between two rooms.
    /// Hero must be in from_room_index (REQ-W4).
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to open the door
    ///   from_room_index (int, required) - Room the hero is currently in
    ///   target_room_index (int, required) - Room on the other side of the door
    /// </summary>
    public class OpenDoorHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "OPEN_DOOR"; } }

        public OpenDoorHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            if (string.IsNullOrEmpty(heroName))
                return "Missing required parameter: hero_name";

            int fromRoomIndex = command.GetInt("from_room_index", -1);
            if (fromRoomIndex < 0)
                return "Missing or invalid parameter: from_room_index";

            int targetRoomIndex = command.GetInt("target_room_index", -2);
            if (targetRoomIndex < -1)
                return "Missing or invalid parameter: target_room_index";

            // Find hero
            Hero hero = FindHeroByName(heroName);
            if (hero == null)
                return "Hero not found: " + heroName;

            if (!hero.IsUsable)
                return "Hero is not usable: " + heroName;

            // Validate hero is in from_room (REQ-W4)
            Room fromRoom = dungeonHook.GetRoomByOpeningIndex(fromRoomIndex);
            if (fromRoom == null)
                return "Invalid from_room_index: " + fromRoomIndex + " (room not found)";

            Room heroRoom = hero.RoomElement.ParentRoom;

            if (heroRoom != fromRoom)
            {
                int actualRoomIndex = dungeonHook.GetRoomIndex(heroRoom);
                return "Hero " + heroName + " is not in from_room (room " + fromRoomIndex
                    + "). Hero is in room " + actualRoomIndex;
            }

            // Find the closed door between from and target
            Door door = FindDoorBetween(fromRoom, targetRoomIndex);
            if (door == null)
                return "No closed door found between room " + fromRoomIndex + " and room " + targetRoomIndex;

            if (door.IsOpening)
                return "Door is already being opened";

            // Cannot open doors while carrying crystal
            if (hero.HasCrystal)
                return "Hero cannot open doors while carrying the crystal";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            int fromRoomIndex = command.GetInt("from_room_index", -1);
            int targetRoomIndex = command.GetInt("target_room_index", -1);

            Hero hero = FindHeroByName(heroName);
            Room fromRoom = dungeonHook.GetRoomByOpeningIndex(fromRoomIndex);

            Door door = FindDoorBetween(fromRoom, targetRoomIndex);

            // MoveToDoor triggers the full open sequence: hero walks to door, door opens,
            // room reveals, mobs spawn, phase transitions
            // MoveToDoor(Door door, bool allowMoveInterruption, Door nextMoveDoorTarget, bool isMoveOrderedByPlayer)
            hero.MoveToDoor(door, false, null, true);

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["from_room_index"] = fromRoomIndex;
            metadata["target_room_index"] = targetRoomIndex;

            return ActionResult.Ok(metadata);
        }

        /// <summary>
        /// Finds a closed door connecting fromRoom to the room at targetRoomIndex.
        /// </summary>
        private Door FindDoorBetween(Room fromRoom, int targetRoomIndex)
        {
            List<Door> openableDoors = Door.OpenableDoors;
            if (openableDoors == null)
                return null;

            for (int i = 0; i < openableDoors.Count; i++)
            {
                Door door = openableDoors[i];
                if (door == null)
                    continue;

                // Check if this door connects fromRoom to the target
                // Note: target room may not be in OpenedRooms yet (it's behind the door)
                // So we check if one side is fromRoom and the other side's OpeningIndex matches target
                // OR if target is -1 (not yet opened), we check Room2 isn't in our indexed rooms
                if (door.Room1 == fromRoom)
                {
                    int otherIndex = dungeonHook.GetRoomIndex(door.Room2);
                    // If other room is already indexed and matches target
                    if (otherIndex == targetRoomIndex)
                        return door;
                    // If target is -1 (unexplored) and other room isn't indexed either
                    if (targetRoomIndex == -1 && otherIndex == -1)
                        return door;
                }
                else if (door.Room2 == fromRoom)
                {
                    int otherIndex = dungeonHook.GetRoomIndex(door.Room1);
                    if (otherIndex == targetRoomIndex)
                        return door;
                    if (targetRoomIndex == -1 && otherIndex == -1)
                        return door;
                }
            }

            return null;
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
