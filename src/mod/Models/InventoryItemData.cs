namespace DotEAgent.Models
{
    /// <summary>
    /// An item in the player's shared inventory (unequipped).
    /// </summary>
    public class BackpackItemData
    {
        public string Name;
        public string Rarity;
        public string Category;       // Slot category this item can go in
    }
}
