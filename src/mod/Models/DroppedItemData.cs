namespace DotEAgent.Models
{
    public class DroppedItemData
    {
        public string Type;         // "Dust", "Equipment", "Chest"
        public string Name;         // Item name (null for dust)
        public int RoomIndex;
        public float DustAmount;    // Only for dust type
        public string Category;     // Slot category for equipment (e.g., "Weapon", "Armor", "Accessory")
        public string WeaponType;   // Weapon sub-type from ItemHeroConfig.CategoryParameters.TypeName (null if not a weapon)
        public string AttackType;   // Attack type from ItemHeroConfig.AttackTypeConfigName (null if not a weapon)
    }
}
