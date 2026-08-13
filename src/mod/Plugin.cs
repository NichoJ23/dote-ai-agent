using System.Collections.Generic;
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

        private void Awake()
        {
            Log = Logger;
            Log.LogInfo(PluginName + " v" + PluginVersion + " loaded!");
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

            // Menu/lifecycle handlers (work before dungeon loads)
            actionRouter.RegisterHandler(new MenuActionHandler("QUERY_MENU_STATE"));
            actionRouter.RegisterHandler(new MenuActionHandler("START_NEW_GAME"));
            actionRouter.RegisterHandler(new MenuActionHandler("CONTINUE_GAME"));
        }

        private void Update()
        {
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
                bool periodicPush = timeSinceLastPush >= 1.0f;

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
