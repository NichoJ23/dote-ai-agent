using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles BUILD_MODULE command: builds a module in a specified room.
    /// The game internally checks industry cost and slot availability.
    /// 
    /// Parameters:
    ///   room_index (int, required) - Room to build in
    ///   module_name (string, required) - Blueprint name of the module to build
    /// </summary>
    public class BuildModuleHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "BUILD_MODULE"; } }

        public BuildModuleHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            int roomIndex = command.GetInt("room_index", -1);
            if (roomIndex < 0)
                return "Missing or invalid parameter: room_index";

            string moduleName = command.GetString("module_name");
            if (string.IsNullOrEmpty(moduleName))
                return "Missing required parameter: module_name";

            Room room = dungeonHook.GetRoomByOpeningIndex(roomIndex);
            if (room == null)
                return "Invalid room_index: " + roomIndex + " (room not found)";

            if (!room.IsFullyOpened)
                return "Room " + roomIndex + " is not fully opened";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            int roomIndex = command.GetInt("room_index", -1);
            string moduleName = command.GetString("module_name");

            Room room = dungeonHook.GetRoomByOpeningIndex(roomIndex);

            GameNetworkManager netManager = SingletonManager.Get<GameNetworkManager>(true);
            ulong playerID = netManager.GetLocalPlayerID();

            // Validate blueprint exists before calling BuildModule
            BluePrintConfig bpConfig = Databases.GetDatabase<BluePrintConfig>(false).GetValue(moduleName);
            if (bpConfig == null)
                return ActionResult.Fail("Unknown module blueprint: " + moduleName);

            // BuildModule(StaticString bpName, ulong builderPlayerID, bool instantBuild,
            //             bool restoration, bool checkRoomPower, bool consumeIndustry, float health)
            // StaticString has implicit conversion from string
            room.BuildModule(moduleName, playerID, false, false, true, true, -1f);

            var metadata = new Dictionary<string, object>();
            metadata["room_index"] = roomIndex;
            metadata["module_name"] = moduleName;

            return ActionResult.Ok(metadata);
        }
    }
}
