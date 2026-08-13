using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles NEXT_FLOOR command: skips the lift dialogue and starts the next floor.
    /// Equivalent to clicking through the EndLevelPanel "Continue" button.
    ///
    /// Call this after a floor is completed (IsLevelOver = true).
    /// Parameters: none
    /// </summary>
    public class NextFloorHandler : IActionHandler
    {
        public string CommandType { get { return "NEXT_FLOOR"; } }

        public NextFloorHandler() { }

        // Accept DungeonHook for interface consistency but don't need it
        public NextFloorHandler(Hooks.DungeonHook dungeonHook) { }

        public string ValidatePreconditions(ActionCommand command)
        {
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return "Dungeon not available";

            if (!dungeon.IsLevelOver)
                return "Level is not over yet";

            IGameControlService gcs = Services.GetService<IGameControlService>();
            if (gcs == null)
                return "GameControlService not available";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);

            // Hide lift/dialogue panels if they're showing
            try
            {
                StoryDialogManager storyMgr = SingletonManager.Get<StoryDialogManager>(true);
                if (storyMgr != null)
                    storyMgr.enabled = false;

                StoryDialogPanel dialogPanel = SingletonManager.Get<StoryDialogPanel>(true);
                if (dialogPanel != null && dialogPanel.IsVisible)
                    dialogPanel.Hide(false);

                Lift lift = SingletonManager.Get<Lift>(true);
                if (lift != null)
                    lift.Hide();

                EndLevelPanel endPanel = SingletonManager.Get<EndLevelPanel>(true);
                if (endPanel != null && endPanel.IsVisible)
                    endPanel.Hide(false);
            }
            catch (System.Exception ex)
            {
                Plugin.Log.LogWarning("NextFloor: Error hiding panels: " + ex.Message);
            }

            // Start next level
            IGameControlService gcs = Services.GetService<IGameControlService>();
            gcs.StartNextLevelSinglePlayerGame();

            Plugin.Log.LogInfo("NextFloor: Starting next floor!");

            var metadata = new Dictionary<string, object>();
            metadata["next_floor"] = dungeon.Level + 1;
            return ActionResult.Ok(metadata);
        }
    }
}
