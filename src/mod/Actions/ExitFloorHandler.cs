using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles EXIT_FLOOR command: triggers level exit when crystal is on exit slot.
    /// Equivalent to pressing the green "EXIT" button in the CrystalLiftPanel.
    /// 
    /// Parameters: none required (crystal must already be on exit slot)
    /// </summary>
    public class ExitFloorHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "EXIT_FLOOR"; } }

        public ExitFloorHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return "Dungeon not available";

            if (dungeon.CurrentCrystalState != CrystalState.PluggedOnExitSlot)
                return "Crystal is not on exit slot (state: " + dungeon.CurrentCrystalState.ToString() + "). Move crystal carrier to exit room first.";

            if (dungeon.IsLevelOver)
                return "Level is already over";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);

            dungeon.LevelOver(true);

            var metadata = new Dictionary<string, object>();
            metadata["exited"] = true;

            Plugin.Log.LogInfo("ExitFloor: Level exit triggered!");
            return ActionResult.Ok(metadata);
        }
    }
}
