namespace DotEAgent.Models
{
    /// <summary>
    /// An item in the player's shared inventory or backpack (unequipped).
    /// </summary>
    public class BackpackItemData
    {
        public string Name;
        public string Rarity;
        public string Category;       // Slot category this item can go in (e.g., "Weapon", "Armor", "Accessory")
        public string WeaponType;     // Weapon sub-type from ItemHeroConfig.CategoryParameters.TypeName (null if not a weapon)
        public string AttackType;     // Attack type from ItemHeroConfig.AttackTypeConfigName (null if not a weapon)
    }
}
