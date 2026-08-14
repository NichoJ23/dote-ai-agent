using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles RETURN_TO_MENU command: transitions the game from any in-game state
    /// (including game-over screen, highscore panel, mid-game) back to the main menu.
    ///
    /// Internally calls IGameControlService.GoBackToMainMenu(true), which:
    ///   1. Stops the game and deletes autosave
    ///   2. Triggers RuntimeState_OutGame transition
    ///   3. OutGameView.Focus() hides GameOverPanel, JournalPanel, VictoryPanel, etc.
    ///   4. Shows the MainMenuPanel
    ///
    /// After this command succeeds, the Python agent can call START_NEW_GAME to begin
    /// a fresh run without any manual UI interaction.
    ///
    /// Parameters: none
    /// </summary>
    public class ReturnToMenuHandler : IActionHandler
    {
        public string CommandType { get { return "RETURN_TO_MENU"; } }

        public ReturnToMenuHandler() { }

        // Accept DungeonHook for interface consistency
        public ReturnToMenuHandler(Hooks.DungeonHook dungeonHook) { }

        public string ValidatePreconditions(ActionCommand command)
        {
            IGameControlService gcs = Services.GetService<IGameControlService>();
            if (gcs == null)
                return "GameControlService not available";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            // Hide any visible game-end panels explicitly before calling GoBackToMainMenu.
            // GoBackToMainMenu triggers the state machine transition which hides them via
            // OutGameView.Focus(), but being explicit ensures clean teardown.
            try
            {
                GameOverPanel gameOverPanel = SingletonManager.Get<GameOverPanel>(false);
                if (gameOverPanel != null && gameOverPanel.IsVisible)
                {
                    gameOverPanel.Hide(true);
                }

                JournalPanel journalPanel = SingletonManager.Get<JournalPanel>(false);
                if (journalPanel != null && journalPanel.IsVisible)
                {
                    journalPanel.Hide(true);
                }

                VictoryPanel victoryPanel = SingletonManager.Get<VictoryPanel>(false);
                if (victoryPanel != null && victoryPanel.IsVisible)
                {
                    victoryPanel.Hide(true);
                }

                EndLevelPanel endLevelPanel = SingletonManager.Get<EndLevelPanel>(false);
                if (endLevelPanel != null && endLevelPanel.IsVisible)
                {
                    endLevelPanel.Hide(true);
                }
            }
            catch (System.Exception ex)
            {
                Plugin.Log.LogWarning("ReturnToMenu: Error hiding panels: " + ex.Message);
            }

            // Call the core transition method — this stops the game and returns to main menu
            IGameControlService gcs = Services.GetService<IGameControlService>();
            gcs.GoBackToMainMenu(true);

            Plugin.Log.LogInfo("ReturnToMenu: Returning to main menu");

            var metadata = new Dictionary<string, object>();
            metadata["returned_to_menu"] = true;
            return ActionResult.Ok(metadata);
        }
    }
}
