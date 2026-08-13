using System.Collections.Generic;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles UNPOWER_ROOM command: removes power from a room.
    /// Rejects attempts to unpower auto-powered rooms (crystal room, etc.).
    /// 
    /// Parameters:
    ///   room_index (int, required) - Room to unpower
    /// </summary>
    public class UnpowerRoomHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "UNPOWER_ROOM"; } }

        public UnpowerRoomHandler(DungeonHook dungeonHook)
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

            if (!room.IsPowered)
                return "Room " + roomIndex + " is already unpowered";

            if (room.IsAutoPowered || room.IsAutoPoweredByEvent)
                return "Room " + roomIndex + " is auto-powered and cannot be unpowered";

            if (room.IsStartRoom)
                return "Cannot unpower the start room";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            int roomIndex = command.GetInt("room_index", -1);

            Room room = dungeonHook.GetRoomByOpeningIndex(roomIndex);

            // TogglePower on a powered room calls UnpowerByPlayer
            room.TogglePower();

            var metadata = new Dictionary<string, object>();
            metadata["room_index"] = roomIndex;

            return ActionResult.Ok(metadata);
        }
    }
}
