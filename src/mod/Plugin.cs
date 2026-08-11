using System.Collections.Generic;
using BepInEx;
using BepInEx.Logging;
using DotEAgent.Models;
using UnityEngine;

namespace DotEAgent
{
    [BepInPlugin(PluginGUID, PluginName, PluginVersion)]
    public class Plugin : BaseUnityPlugin
    {
        public const string PluginGUID = "com.doteagent.mod";
        public const string PluginName = "DotE Agent Mod";
        public const string PluginVersion = "0.2.0";

        internal static ManualLogSource Log;

        private StateManager stateManager;
        private int lastLoggedTurn = -1;
        private int lastMobCount = 0;

        private void Awake()
        {
            Log = Logger;
            Log.LogInfo(PluginName + " v" + PluginVersion + " loaded!");
            stateManager = new StateManager();
        }

        private void Update()
        {
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

            // Track mob changes mid-turn (they spawn after turn increments)
            lastMobCount = state.Mobs.Count;
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
