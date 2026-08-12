using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts global resource balances (Industry, Food, Science, Dust) and per-turn production.
    /// </summary>
    public class ResourceHook : IStateHook
    {
        private Dungeon dungeon;

        public string HookId { get { return "resources"; } }
        public bool IsBound { get { return dungeon != null; } }

        public bool TryBind()
        {
            dungeon = SingletonManager.Get<Dungeon>(false);
            return dungeon != null;
        }

        public object ExtractState()
        {
            if (!IsBound)
                return null;

            // Re-acquire dungeon in case it changed between floors
            dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return null;

            // Get player via multiple fallback paths
            Player player = Player.LocalPlayer;
            if (player == null)
            {
                // Fallback: try to get player from the player ID list
                ulong[] ids = Player.GetPlayerIDs();
                if (ids != null && ids.Length > 0)
                    player = Player.GetPlayerByID(ids[0], false);
            }

            var state = new ResourceStateData();

            // Player resources (Food, Industry, Science) - requires Player reference
            if (player != null)
            {
                state.Industry = player.IndustryStock;
                state.Food = player.FoodStock;
                state.Science = player.ScienceStock;
            }

            // Dungeon resources (Dust and production rates) - always available
            state.Dust = dungeon.DustStock;
            state.DustMax = dungeon.GetMaxDustStock();
            state.IndustryPerTurn = dungeon.GetIndustryProd();
            state.FoodPerTurn = dungeon.GetFoodProd();
            state.SciencePerTurn = dungeon.GetScienceProd();
            state.DustPerTurn = dungeon.GetDustProd();
            state.RoomPowerCost = dungeon.GetRoomPowerDustCost();
            state.PoweredRoomCount = dungeon.GetPoweredRoomCount();

            return state;
        }
    }
}
