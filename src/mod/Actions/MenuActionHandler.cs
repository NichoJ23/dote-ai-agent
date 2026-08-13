using System.Collections.Generic;
using Amplitude;
using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles menu/lifecycle commands that work outside of the dungeon:
    /// - QUERY_MENU_STATE: Returns available heroes, ships, save info, and current game state
    /// - START_NEW_GAME: Sets ship, heroes, difficulty and launches a new game
    /// - CONTINUE_GAME: Loads the best available save
    /// </summary>
    public class MenuActionHandler : IActionHandler
    {
        private readonly string commandType;

        public string CommandType { get { return commandType; } }

        public MenuActionHandler(string commandType)
        {
            this.commandType = commandType;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            // Menu commands have no preconditions — they can be called at any time
            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            switch (command.Command)
            {
                case "QUERY_MENU_STATE":
                    return ExecuteQueryMenuState();
                case "START_NEW_GAME":
                    return ExecuteStartNewGame(command);
                case "CONTINUE_GAME":
                    return ExecuteContinueGame(command);
                default:
                    return ActionResult.Fail("Unknown menu command: " + command.Command);
            }
        }

        private ActionResult ExecuteQueryMenuState()
        {
            var metadata = new Dictionary<string, object>();

            // Determine current state
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            bool inDungeon = dungeon != null && dungeon.OpenedRooms != null && dungeon.OpenedRooms.Count > 0;
            metadata["in_dungeon"] = inDungeon;

            // Check for saved games
            bool hasSave = false;
            try
            {
                hasSave = GameSave.HasSinglePlayerSaveFile();
            }
            catch (System.Exception ex)
            {
                Plugin.Log.LogWarning("MenuAction: Failed to check save files: " + ex.Message);
            }
            metadata["has_save"] = hasSave;

            // Get available heroes
            List<string> heroNames = new List<string>();
            try
            {
                var heroDb = Databases.GetDatabase<HeroConfig>(false);
                if (heroDb != null)
                {
                    HeroConfig[] allHeroes = heroDb.GetValues();
                    for (int i = 0; i < allHeroes.Length; i++)
                    {
                        if (allHeroes[i] != null)
                        {
                            heroNames.Add(allHeroes[i].Name.ToString());
                        }
                    }
                }
            }
            catch (System.Exception ex)
            {
                Plugin.Log.LogWarning("MenuAction: Failed to get hero list: " + ex.Message);
            }
            metadata["available_heroes"] = heroNames;

            // Get selectable heroes (unlocked by player)
            List<string> selectableHeroes = new List<string>();
            try
            {
                var selectable = UserProfile.GetSelectableHeroes(false);
                if (selectable != null)
                {
                    for (int i = 0; i < selectable.Length; i++)
                    {
                        if (selectable[i].Status == HeroStatus.Unlocked)
                        {
                            selectableHeroes.Add(selectable[i].ConfigName.ToString());
                        }
                    }
                }
            }
            catch (System.Exception ex)
            {
                Plugin.Log.LogWarning("MenuAction: Failed to get selectable heroes: " + ex.Message);
            }
            metadata["selectable_heroes"] = selectableHeroes;

            // Get available ships
            List<string> shipNames = new List<string>();
            try
            {
                var shipDb = Databases.GetDatabase<ShipConfig>(false);
                if (shipDb != null)
                {
                    ShipConfig[] allShips = shipDb.GetValues();
                    for (int i = 0; i < allShips.Length; i++)
                    {
                        if (allShips[i] != null)
                        {
                            shipNames.Add(allShips[i].Name.ToString());
                        }
                    }
                }
            }
            catch (System.Exception ex)
            {
                Plugin.Log.LogWarning("MenuAction: Failed to get ship list: " + ex.Message);
            }
            metadata["available_ships"] = shipNames;

            return ActionResult.Ok(metadata);
        }

        private ActionResult ExecuteStartNewGame(ActionCommand command)
        {
            // Extract parameters
            string shipName = command.GetString("ship_name");
            string difficulty = command.GetString("difficulty");
            List<string> heroNames = GetStringList(command, "hero_names");

            // Set ship (use first available if not specified)
            if (!string.IsNullOrEmpty(shipName))
            {
                Dungeon.SetShip(new StaticString(shipName));
                Plugin.Log.LogInfo("MenuAction: Ship set to " + shipName);
            }
            else
            {
                var shipDb = Databases.GetDatabase<ShipConfig>(false);
                if (shipDb != null && shipDb.GetValues().Length > 0)
                {
                    Dungeon.SetShip(shipDb.GetValues()[0].Name);
                    Plugin.Log.LogInfo("MenuAction: Ship defaulted to " + shipDb.GetValues()[0].Name);
                }
            }

            // Set difficulty
            GameDifficulty gameDifficulty = GameDifficulty.Normal;
            if (!string.IsNullOrEmpty(difficulty))
            {
                switch (difficulty.ToLower())
                {
                    case "easy": gameDifficulty = GameDifficulty.Easy; break;
                    case "normal": gameDifficulty = GameDifficulty.Normal; break;
                }
            }
            Dungeon.SetGameDifficulty(gameDifficulty);
            Plugin.Log.LogInfo("MenuAction: Difficulty set to " + gameDifficulty);

            // Set heroes
            if (heroNames != null && heroNames.Count > 0)
            {
                StaticString[] heroes = new StaticString[heroNames.Count];
                for (int i = 0; i < heroNames.Count; i++)
                {
                    heroes[i] = new StaticString(heroNames[i]);
                }
                Dungeon.SetSelectedHeroes(heroes);
                Plugin.Log.LogInfo("MenuAction: Heroes set to [" + string.Join(", ", heroNames.ToArray()) + "]");
            }

            // Launch the game
            try
            {
                // Ensure input mode is set correctly (normally done by MainMenuPanel)
                IInputService inputService = Services.GetService<IInputService>();
                if (inputService != null)
                    inputService.SetInputMode(InputMode.MouseKeyboard);

                IGameControlService gcs = Services.GetService<IGameControlService>();
                if (gcs == null)
                {
                    return ActionResult.Fail("GameControlService not available");
                }
                gcs.StartNewSinglePlayerGame();
                Plugin.Log.LogInfo("MenuAction: New game started!");
                return ActionResult.Ok();
            }
            catch (System.Exception ex)
            {
                return ActionResult.Fail("Failed to start new game: " + ex.Message);
            }
        }

        private ActionResult ExecuteContinueGame(ActionCommand command)
        {
            bool hasSave = false;
            try
            {
                hasSave = GameSave.HasSinglePlayerSaveFile();
            }
            catch (System.Exception ex)
            {
                return ActionResult.Fail("Cannot check save file: " + ex.Message);
            }

            if (!hasSave)
            {
                return ActionResult.Fail("No save file found");
            }

            try
            {
                string saveKey = null;
                GameSave.GetBestSPSaveData(ref saveKey, true);

                if (saveKey == null)
                {
                    return ActionResult.Fail("Could not determine save key");
                }

                IGameControlService gcs = Services.GetService<IGameControlService>();
                if (gcs == null)
                {
                    return ActionResult.Fail("GameControlService not available");
                }

                // Ensure input mode is set correctly (normally done by MainMenuPanel)
                IInputService inputService = Services.GetService<IInputService>();
                if (inputService != null)
                    inputService.SetInputMode(InputMode.MouseKeyboard);

                gcs.StartSavedSinglePlayerGame(saveKey);
                Plugin.Log.LogInfo("MenuAction: Continuing saved game (key=" + saveKey + ")");
                return ActionResult.Ok();
            }
            catch (System.Exception ex)
            {
                return ActionResult.Fail("Failed to continue game: " + ex.Message);
            }
        }

        /// <summary>
        /// Helper to extract a list of strings from a parameter that might be
        /// a List of objects (from JSON array deserialization).
        /// </summary>
        private static List<string> GetStringList(ActionCommand command, string key)
        {
            object val;
            if (!command.Parameters.TryGetValue(key, out val) || val == null)
                return null;

            // The JSON deserializer produces List<object> for arrays
            var list = val as List<object>;
            if (list == null)
                return null;

            var result = new List<string>();
            for (int i = 0; i < list.Count; i++)
            {
                if (list[i] != null)
                    result.Add(list[i].ToString());
            }
            return result;
        }
    }
}
