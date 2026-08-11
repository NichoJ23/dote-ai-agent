namespace DotEAgent.Models
{
    /// <summary>
    /// Serializable resource state extracted by ResourceHook.
    /// </summary>
    public class ResourceStateData
    {
        public float Industry;
        public float Food;
        public float Science;
        public float Dust;
        public float DustMax;
        public float IndustryPerTurn;
        public float FoodPerTurn;
        public float SciencePerTurn;
        public float DustPerTurn;
        public float RoomPowerCost;
        public int PoweredRoomCount;
    }
}
