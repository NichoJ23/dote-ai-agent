namespace DotEAgent.Models
{
    public class DroppedItemData
    {
        public string Type;         // "Dust", "Equipment", "Chest"
        public string Name;         // Item name (null for dust)
        public int RoomIndex;
        public float DustAmount;    // Only for dust type
    }
}
