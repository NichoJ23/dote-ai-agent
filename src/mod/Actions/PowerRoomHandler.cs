using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles POWER_ROOM command: powers a room (costs dust).
    /// 
    /// Parameters:
    ///   room_index (int, required) - Room to power
    /// </summary>
    public class PowerRoomHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "POWER_ROOM"; } }

        public PowerRoomHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            int roomIndex = command.GetInt("room_index", -1);
            if (roomIndex < 0)
                return "Missing or invalid parameter: room_index";

            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null || dungeon.OpenedRooms == null)
                return "Dungeon not available";

            List<Room> rooms = dungeon.OpenedRooms;
            if (roomIndex >= rooms.Count)
                return "Invalid room_index: " + roomIndex;

            Room room = rooms[roomIndex];

            if (room.IsPowered)
                return "Room " + roomIndex + " is already powered";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            int roomIndex = command.GetInt("room_index", -1);

            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            Room room = dungeon.OpenedRooms[roomIndex];

            // TogglePower handles finding a power path and powering the room
            bool success = room.TogglePower();

            if (!success)
                return ActionResult.Fail("Could not power room " + roomIndex + " (no power path or insufficient dust)");

            var metadata = new Dictionary<string, object>();
            metadata["room_index"] = roomIndex;

            return ActionResult.Ok(metadata);
        }
    }
}
