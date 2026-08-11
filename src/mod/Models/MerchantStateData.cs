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
    }
}
