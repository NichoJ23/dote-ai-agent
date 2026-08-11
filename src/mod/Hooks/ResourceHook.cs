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
        private Player player;

        public string HookId { get { return "resources"; } }
        public bool IsBound { get { return dungeon != null && player != null; } }

        public bool TryBind()
        {
            dungeon = SingletonManager.Get<Dungeon>(false);
            player = Player.LocalPlayer;
            return dungeon != null && player != null;
        }

        public object ExtractState()
        {
            if (!IsBound)
                return null;

            // Re-check Player.LocalPlayer in case it changed (e.g., between floors)
            player = Player.LocalPlayer;
            if (player == null)
                return null;

            var state = new ResourceStateData();
            state.Industry = player.IndustryStock;
            state.Food = player.FoodStock;
            state.Science = player.ScienceStock;
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
