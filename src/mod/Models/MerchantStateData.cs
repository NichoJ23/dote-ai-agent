using System.Collections.Generic;

namespace DotEAgent.Models
{
    public class MerchantStateData
    {
        public int RoomIndex;
        public string CurrencyType;        // "Dust", "Food", "Industry", "Science"
        public List<MerchantItemData> Items;
    }

    public class MerchantItemData
    {
        public string Name;
        public string Rarity;
        public float Cost;
        public string Category;            // Slot category (e.g., "Weapon", "Armor", "Accessory")
        public string WeaponType;          // Weapon sub-type from ItemHeroConfig.CategoryParameters.TypeName (null if not a weapon)
        public string AttackType;          // Attack type from ItemHeroConfig.AttackTypeConfigName (null if not a weapon)
    }
}
