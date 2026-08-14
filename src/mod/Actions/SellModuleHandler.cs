using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles SELL_MODULE command: destroys a built module in a room.
    /// The game internally handles partial industry refund.
    /// Cannot destroy unremovable modules (crystal module) or modules currently being built.
    /// 
    /// Parameters:
    ///   room_index (int, required) - Room containing the module
    ///   module_name (string, required) - Name of the module to destroy (blueprint name or config name)
    /// </summary>
    public class SellModuleHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "SELL_MODULE"; } }

        public SellModuleHandler(DungeonHook dungeonHook)
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

            // Find the module in the room
            Module module = FindModuleInRoom(room, moduleName);
            if (module == null)
                return "Module not found in room " + roomIndex + ": " + moduleName;

            if (module.IsBuilding)
                return "Cannot destroy a module that is still being built";

            if (module.Config != null && module.Config.Unremovable)
                return "Cannot destroy unremovable module: " + moduleName;

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            int roomIndex = command.GetInt("room_index", -1);
            string moduleName = command.GetString("module_name");

            Room room = dungeonHook.GetRoomByOpeningIndex(roomIndex);
            Module module = FindModuleInRoom(room, moduleName);

            // DoRemove(false) = don't check ownership (we own it as local player)
            module.DoRemove(false);

            var metadata = new Dictionary<string, object>();
            metadata["room_index"] = roomIndex;
            metadata["module_name"] = moduleName;

            return ActionResult.Ok(metadata);
        }

        /// <summary>
        /// Find a module in a room by its blueprint name or config name.
        /// Checks both major module and minor modules.
        /// </summary>
        private Module FindModuleInRoom(Room room, string moduleName)
        {
            if (room == null)
                return null;

            // Check major module
            if (room.MajorModule != null)
            {
                if (MatchesModuleName(room.MajorModule, moduleName))
                    return room.MajorModule;
            }

            // Check minor modules
            if (room.MinorModules != null)
            {
                for (int i = 0; i < room.MinorModules.Count; i++)
                {
                    MinorModule minor = room.MinorModules[i];
                    if (minor == null)
                        continue;
                    if (MatchesModuleName(minor, moduleName))
                        return minor;
                }
            }

            return null;
        }

        /// <summary>
        /// Check if a module matches the given name.
        /// Matches against blueprint name (e.g., "MajorModule_Major0002_LVL1")
        /// or config name (e.g., "Major0002").
        /// </summary>
        private bool MatchesModuleName(Module module, string name)
        {
            if (module == null || module.Config == null)
                return false;

            // Match full blueprint/config name
            string configName = module.Config.Name != null ? module.Config.Name.ToString() : "";
            if (configName == name)
                return true;

            // Match against the GetConfigName which may include level suffix
            string fullName = module.GetConfigName();
            if (!string.IsNullOrEmpty(fullName) && fullName == name)
                return true;

            // Match partial (blueprint pattern like "MajorModule_Major0002_LVL1")
            if (!string.IsNullOrEmpty(configName) && name.Contains(configName))
                return true;

            return false;
        }
    }
}
