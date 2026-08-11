using System.Collections.Generic;

namespace DotEAgent.Models
{
    /// <summary>
    /// Complete game state snapshot combining all hooks.
    /// This is the payload that will be sent to the Python agent over TCP.
    /// </summary>
    public class GameStatePayload
    {
        public int Turn;
        public int Floor;
        public string GamePhase;
        public string CrystalState;
        public ResourceStateData Resources;
        public List<RoomStateData> Rooms;
        public List<DoorStateData> ClosedDoors;
        public List<HeroStateData> Heroes;
        public List<MobStateData> Mobs;
        public List<MerchantStateData> Merchants;
        public List<RecruitableHeroData> RecruitableHeroes;
        public List<DroppedItemData> DroppedItems;
        public List<BackpackItemData> BackpackItems;      // Kept between floors (4 slots)
        public List<BackpackItemData> SharedInventoryItems; // Lost at end of floor
        public int ExitRoomIndex;
        public int StartRoomIndex;
    }
}
