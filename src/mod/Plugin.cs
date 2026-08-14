using System.Collections.Generic;
using System.IO;
using Amplitude;
using Amplitude.Unity.Framework;
using BepInEx;
using BepInEx.Logging;
using DotEAgent.Actions;
using DotEAgent.Ipc;
using DotEAgent.Models;
using UnityEngine;

namespace DotEAgent
{
    [BepInPlugin(PluginGUID, PluginName, PluginVersion)]
    public class Plugin : BaseUnityPlugin
    {
        public const string PluginGUID = "com.doteagent.mod";
        public const string PluginName = "DotE Agent Mod";
        public const string PluginVersion = "0.3.0";

        internal static ManualLogSource Log;

        private StateManager stateManager;
        private IpcBridge ipcBridge;
        private ActionRouter actionRouter;
        private int lastLoggedTurn = -1;
        private int lastMobCount = 0;
        private int lastSentTurn = -1;
        private string lastSentPhase = "";
        private bool wasStateConnected = false;
        private float lastStateSentTime = 0f;
        private float actionTimeoutSeconds = 30f;
        private bool pausedForTimeout = false;

        // Training mode settings (read from BepInEx/plugins/dote_training.cfg)
        private bool trainingMode = false;
        private float targetTimeScale = 2f;
        private int trainingResWidth = 640;
        private int trainingResHeight = 480;

        private void Awake()
        {
            Log = Logger;
            Log.LogInfo(PluginName + " v" + PluginVersion + " loaded!");

            // CRITICAL: Force runInBackground immediately before anything else.
            // Without this, Unity stops the game loop when the window loses focus,
            // which causes the game to "crash" (actually just freeze) when unfocused.
            // Must be set before the game's own code has a chance to override it.
            UnityEngine.Application.runInBackground = true;

            // Load training config from a simple text file next to the plugin DLL
            // File: BepInEx/plugins/dote_training.cfg
            // Format:
            //   training_mode=true
            //   time_scale=4
            LoadTrainingConfig();

            if (trainingMode)
            {
                ApplyTrainingMode();
            }
            else
            {
                // Normal mode: just apply time scale, and restore fullscreen
                // (in case a previous training session left resolution in a bad state)
                Time.timeScale = targetTimeScale;
                Screen.fullScreen = true;
                Log.LogInfo("Game speed set to " + targetTimeScale + "x (normal mode)");
            }

            stateManager = new StateManager();

            ipcBridge = new IpcBridge();
            ipcBridge.Start();

            actionRouter = new ActionRouter(ipcBridge);
            actionRouter.RegisterHandler(new MoveHeroHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new OpenDoorHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new BuildModuleHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new RepairModuleHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new PowerRoomHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new UnpowerRoomHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new RecruitHeroHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new BuyFromMerchantHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new EquipItemHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new UnequipItemHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new CollectItemHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new PickUpCrystalHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new LevelUpHeroHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new HealHeroHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new ResearchHandler(stateManager.GetDungeonHook()));

            // Floor exit handler
            actionRouter.RegisterHandler(new ExitFloorHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new PlugCrystalExitHandler(stateManager.GetDungeonHook()));
            actionRouter.RegisterHandler(new NextFloorHandler(stateManager.GetDungeonHook()));

            // Menu/lifecycle handlers (work before dungeon loads)
            actionRouter.RegisterHandler(new MenuActionHandler("QUERY_MENU_STATE"));
            actionRouter.RegisterHandler(new MenuActionHandler("START_NEW_GAME"));
            actionRouter.RegisterHandler(new MenuActionHandler("CONTINUE_GAME"));
            actionRouter.RegisterHandler(new ReturnToMenuHandler());
        }

        private void Update()
        {
            // Enforce game speed every frame (game resets timeScale on unpause/transitions)
            if (Time.timeScale != 0f && Time.timeScale != targetTimeScale)
            {
                Time.timeScale = targetTimeScale;
            }

            // In training mode, keep enforcing windowed resolution and runInBackground
            // because the game's own code re-applies fullscreen on scene loads
            // and may disable runInBackground
            if (trainingMode)
            {
                if (Screen.fullScreen)
                {
                    Screen.fullScreen = false;
                    Screen.SetResolution(trainingResWidth, trainingResHeight, false);
                }
                // Must enforce every frame — game code resets this
                UnityEngine.Application.runInBackground = true;
            }

            // Always accept IPC clients and process actions (even before dungeon loads)
            // This allows menu commands like QUERY_MENU_STATE and START_NEW_GAME
            ipcBridge.AcceptClients();
            actionRouter.ProcessActions();

            // Try to bind if not yet bound
            if (!stateManager.IsBound)
            {
                if (stateManager.TryBind())
                {
                    Log.LogInfo("StateManager bound - all hooks active!");
                }
                return;
            }

            // Extract full state
            GameStatePayload state = stateManager.ExtractFullState();
            if (state == null)
                return;

            // Log once per turn
            if (state.Turn != lastLoggedTurn)
            {
                lastLoggedTurn = state.Turn;
                LogFullState(state);
            }

            // Push state to Python agent when turn or phase changes, on new connection,
            // or periodically (every 1s) so agent can track hero movement
            if (ipcBridge.IsStateConnected)
            {
                bool newConnection = !wasStateConnected;
                wasStateConnected = true;

                float timeSinceLastPush = Time.unscaledTime - lastStateSentTime;
                float pushInterval = (state.GamePhase == "Action") 
                    ? 0.5f / Time.timeScale 
                    : 1.0f / Time.timeScale;
                bool periodicPush = timeSinceLastPush >= pushInterval;

                if (newConnection || state.Turn != lastSentTurn || state.GamePhase != lastSentPhase || periodicPush)
                {
                    string json = JsonSerializer.Serialize(state);
                    ipcBridge.SendState(json);
                    lastSentTurn = state.Turn;
                    lastSentPhase = state.GamePhase;
                    lastStateSentTime = Time.unscaledTime;
                    if (newConnection)
                        Log.LogInfo("IPC: Sent initial state to newly connected client");
                }
            }
            else
            {
                wasStateConnected = false;
            }

            // If we received an action while paused, unpause immediately
            if (pausedForTimeout && actionRouter.LastActionReceivedThisFrame)
            {
                pausedForTimeout = false;
                IGameControlService gcs = Services.GetService<IGameControlService>();
                if (gcs != null)
                    gcs.SetGamePause(false, true);
                lastStateSentTime = Time.unscaledTime;
                Log.LogInfo("IPC: Agent responded - game resumed");
            }

            // Timeout handling: if Python agent is connected but not responding
            // during Action phase, pause the game to prevent it from running uncontrolled.
            if (!pausedForTimeout && ipcBridge.IsActionConnected && state.GamePhase == "Action")
            {
                float elapsed = Time.unscaledTime - lastStateSentTime;
                if (elapsed > actionTimeoutSeconds)
                {
                    pausedForTimeout = true;
                    IGameControlService gcs = Services.GetService<IGameControlService>();
                    if (gcs != null)
                        gcs.SetGamePause(true, true);
                    Log.LogWarning("IPC: Python agent timeout (" + actionTimeoutSeconds + "s) - game paused");
                }
            }

            // Reset timeout when agent responds (even if not paused yet)
            if (actionRouter.LastActionReceivedThisFrame)
            {
                lastStateSentTime = Time.unscaledTime;
            }

            // Push fresh state after every successful action so agent always has ground truth
            if (actionRouter.LastActionSucceeded && ipcBridge.IsStateConnected)
            {
                GameStatePayload freshState = stateManager.ExtractFullState();
                if (freshState != null)
                {
                    string json = JsonSerializer.Serialize(freshState);
                    ipcBridge.SendState(json);
                    lastSentTurn = freshState.Turn;
                    lastSentPhase = freshState.GamePhase;
                    lastStateSentTime = Time.unscaledTime;
                }
            }

            // Track mob changes mid-turn (they spawn after turn increments)
            lastMobCount = state.Mobs.Count;
        }

        private void OnDestroy()
        {
            if (ipcBridge != null)
            {
                ipcBridge.Dispose();
                ipcBridge = null;
            }
        }

        /// <summary>
        /// Apply all training-mode optimizations to minimize GPU/CPU overhead.
        /// Called once in Awake() when Training.Enabled = true in config.
        /// </summary>
        private void ApplyTrainingMode()
        {
            Log.LogInfo("=== TRAINING MODE ENABLED ===");

            // 1. Uncap framerate (remove VSync bottleneck)
            QualitySettings.vSyncCount = 0;
            UnityEngine.Application.targetFrameRate = -1;  // Uncapped
            Log.LogInfo("  VSync disabled, framerate uncapped");

            // 2. Drop to lowest quality level
            QualitySettings.SetQualityLevel(0, true);
            Log.LogInfo("  Quality set to lowest level");

            // 3. Disable shadows (via distance = 0 for Unity 5.0.3 compatibility)
            QualitySettings.shadowDistance = 0f;
            Log.LogInfo("  Shadows disabled (distance=0)");

            // 4. Disable anti-aliasing
            QualitySettings.antiAliasing = 0;
            Log.LogInfo("  Anti-aliasing disabled");

            // 5. Reduce texture quality (1/8 res)
            QualitySettings.masterTextureLimit = 3;
            Log.LogInfo("  Texture resolution reduced to 1/8");

            // 6. Disable particle raycast budget
            QualitySettings.particleRaycastBudget = 0;
            Log.LogInfo("  Particle raycast budget set to 0");

            // 7. Reduce pixel light count
            QualitySettings.pixelLightCount = 0;
            Log.LogInfo("  Pixel light count set to 0");

            // 9. Mute audio (saves CPU on mixing/decoding)
            AudioListener.volume = 0f;
            AudioListener.pause = true;
            Log.LogInfo("  Audio muted and paused");

            // 10. Force the game to keep running when unfocused (critical for training —
            // without this, Unity suspends the game loop when the window loses focus)
            UnityEngine.Application.runInBackground = true;
            Log.LogInfo("  runInBackground enabled (game won't freeze when unfocused)");

            // 11. Force small windowed mode (reduces pixel fill dramatically)
            // Note: also re-applied in Update() because the game overrides this during loading
            Screen.SetResolution(trainingResWidth, trainingResHeight, false);
            Log.LogInfo("  Resolution forced to " + trainingResWidth + "x" + trainingResHeight + " windowed");

            // 11. Apply game speed
            Time.timeScale = targetTimeScale;
            Log.LogInfo("  Game speed set to " + targetTimeScale + "x");

            // 10. Try to stop particle systems to save GPU draw calls
            try
            {
                ParticleSystem[] particles = Object.FindObjectsOfType<ParticleSystem>();
                foreach (ParticleSystem ps in particles)
                {
                    ps.Stop();
                }
                Log.LogInfo("  Stopped " + particles.Length + " particle systems");
            }
            catch (System.Exception ex)
            {
                Log.LogWarning("  Could not stop particles: " + ex.Message);
            }

            Log.LogInfo("=== Training mode active: GPU usage minimized ===");
        }

        /// <summary>
        /// Load training configuration from a simple key=value text file.
        /// File location: BepInEx/plugins/dote_training.cfg
        /// </summary>
        private void LoadTrainingConfig()
        {
            string pluginDir = System.IO.Path.GetDirectoryName(
                typeof(Plugin).Assembly.Location);
            string cfgPath = System.IO.Path.Combine(pluginDir, "dote_training.cfg");

            if (!File.Exists(cfgPath))
            {
                // Create a default config file for convenience
                try
                {
                    File.WriteAllText(cfgPath,
                        "# DotE Agent Training Configuration\n" +
                        "# Set training_mode=true to enable all GPU/CPU optimizations\n" +
                        "# time_scale: game speed multiplier (2=default, 4-8 for training)\n" +
                        "# resolution_width/height: window size in training mode (smaller = less GPU)\n" +
                        "#   640x480 = safe, 100x100 = minimal GPU, 64x64 = experimental\n" +
                        "\n" +
                        "training_mode=false\n" +
                        "time_scale=2\n" +
                        "resolution_width=640\n" +
                        "resolution_height=480\n");
                    Log.LogInfo("Created default config: " + cfgPath);
                }
                catch (System.Exception ex)
                {
                    Log.LogWarning("Could not create config file: " + ex.Message);
                }
                return;
            }

            try
            {
                string[] lines = File.ReadAllLines(cfgPath);
                foreach (string line in lines)
                {
                    string trimmed = line.Trim();
                    if (trimmed.StartsWith("#") || !trimmed.Contains("="))
                        continue;

                    string[] parts = trimmed.Split(new char[] { '=' }, 2);
                    string key = parts[0].Trim().ToLower();
                    string value = parts[1].Trim().ToLower();

                    if (key == "training_mode")
                    {
                        trainingMode = (value == "true" || value == "1" || value == "yes");
                    }
                    else if (key == "time_scale")
                    {
                        float parsed;
                        if (float.TryParse(value, out parsed) && parsed > 0f)
                        {
                            targetTimeScale = parsed;
                        }
                    }
                    else if (key == "resolution_width")
                    {
                        int parsed;
                        if (int.TryParse(value, out parsed) && parsed > 0)
                        {
                            trainingResWidth = parsed;
                        }
                    }
                    else if (key == "resolution_height")
                    {
                        int parsed;
                        if (int.TryParse(value, out parsed) && parsed > 0)
                        {
                            trainingResHeight = parsed;
                        }
                    }
                }

                Log.LogInfo("Config loaded: training_mode=" + trainingMode + ", time_scale=" + targetTimeScale);
            }
            catch (System.Exception ex)
            {
                Log.LogWarning("Failed to read config: " + ex.Message);
            }
        }

        private void LogFullState(GameStatePayload state)
        {
            // Header
            Log.LogInfo(string.Format(
                "[Turn {0}] Floor {1} | Phase: {2} | Crystal: {3} | Rooms: {4} | Doors: {5} | Heroes: {6} | Mobs: {7}",
                state.Turn, state.Floor, state.GamePhase, state.CrystalState,
                state.Rooms.Count, state.ClosedDoors.Count,
                state.Heroes.Count, state.Mobs.Count));

            // Resources
            if (state.Resources != null)
            {
                ResourceStateData r = state.Resources;
                Log.LogInfo(string.Format(
                    "  Resources: Dust={0}/{1} Food={2} Ind={3} Sci={4} | PerTurn: D={5} F={6} I={7} S={8} | Power: {9}cost x{10}rooms",
                    r.Dust, r.DustMax, r.Food, r.Industry, r.Science,
                    r.DustPerTurn, r.FoodPerTurn, r.IndustryPerTurn, r.SciencePerTurn,
                    r.RoomPowerCost, r.PoweredRoomCount));
            }

            // Rooms
            for (int i = 0; i < state.Rooms.Count; i++)
            {
                RoomStateData room = state.Rooms[i];
                string flags = "";
                if (room.IsAutoPowered) flags += "auto ";
                if (room.IsExitRoom) flags += "exit ";
                if (room.IsStartRoom) flags += "start ";
                if (room.SuffersEMP) flags += "EMP(" + room.EmpTurnsRemaining + ") ";
                if (room.HasArtifact) flags += "ARTIFACT ";
                if (room.HasStele) flags += "STELE ";

                Log.LogDebug(string.Format(
                    "  Room[{0}]: pow={1} heroes={2} mobs={3} adj=[{4}] major={5} minor={6} dust={7}{8}",
                    room.Index,
                    room.IsPowered ? "Y" : "N",
                    room.HeroCount, room.MobCount,
                    string.Join(",", room.AdjacentRoomIndices.ConvertAll(x => x.ToString()).ToArray()),
                    room.MajorModuleName ?? "-",
                    room.MinorModuleNames.Count,
                    room.DustLootAmount,
                    flags.Length > 0 ? " [" + flags.TrimEnd() + "]" : ""));
            }

            // Heroes
            for (int i = 0; i < state.Heroes.Count; i++)
            {
                HeroStateData h = state.Heroes[i];
                string status = "";
                if (h.HasCrystal) status += "CRYSTAL ";
                if (h.IsOperating) status += "OP:" + h.OperatingModuleName + " ";
                Log.LogInfo(string.Format(
                    "  Hero[{0}]: {1} ({2}) Room={3} HP={4}/{5} Lvl={6} Skills={7}A+{8}P Equip={9}{10}",
                    i, h.Name, h.Faction, h.RoomIndex,
                    h.Hp, h.MaxHp, h.Level,
                    h.ActiveSkills.Count, h.PassiveSkills.Count,
                    h.Equipment.Count,
                    status.Length > 0 ? " [" + status.TrimEnd() + "]" : ""));
            }

            // Merchants
            for (int i = 0; i < state.Merchants.Count; i++)
            {
                MerchantStateData m = state.Merchants[i];
                Log.LogInfo(string.Format("  Merchant Room[{0}]: {1} items ({2})",
                    m.RoomIndex, m.Items.Count, m.CurrencyType));
            }

            // Recruits
            for (int i = 0; i < state.RecruitableHeroes.Count; i++)
            {
                RecruitableHeroData r = state.RecruitableHeroes[i];
                Log.LogInfo(string.Format("  Recruit Room[{0}]: {1} ({2}) Passives=[{3}]",
                    r.RoomIndex, r.Name, r.Faction,
                    string.Join(",", r.PassiveSkillNames.ToArray())));
            }

            // Dropped items
            if (state.DroppedItems.Count > 0)
            {
                Log.LogInfo(string.Format("  Items on ground: {0}", state.DroppedItems.Count));
            }

            // Inventory
            if (state.BackpackItems.Count > 0 || state.SharedInventoryItems.Count > 0)
            {
                Log.LogInfo(string.Format("  Inventory: Backpack={0}/4, Shared={1} (lost on floor exit)",
                    state.BackpackItems.Count, state.SharedInventoryItems.Count));
            }
        }

    }
}
