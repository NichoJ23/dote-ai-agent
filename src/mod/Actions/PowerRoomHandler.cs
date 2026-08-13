using System.Collections.Generic;
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

            Room room = dungeonHook.GetRoomByOpeningIndex(roomIndex);
            if (room == null)
                return "Invalid room_index: " + roomIndex + " (room not found)";

            if (room.IsPowered)
                return "Room " + roomIndex + " is already powered";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            int roomIndex = command.GetInt("room_index", -1);

            Room room = dungeonHook.GetRoomByOpeningIndex(roomIndex);

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
