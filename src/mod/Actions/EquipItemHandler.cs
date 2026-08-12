using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles EQUIP_ITEM command: equips an item from shared/backpack inventory onto a hero.
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to equip the item on
    ///   item_name (string, required) - Name of the item to equip
    /// </summary>
    public class EquipItemHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "EQUIP_ITEM"; } }

        public EquipItemHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            if (string.IsNullOrEmpty(heroName))
                return "Missing required parameter: hero_name";

            string itemName = command.GetString("item_name");
            if (string.IsNullOrEmpty(itemName))
                return "Missing required parameter: item_name";

            Hero hero = FindHeroByName(heroName);
            if (hero == null)
                return "Hero not found: " + heroName;

            // Find item in shared or backpack inventory
            InventoryItem item = FindItemInInventories(itemName);
            if (item == null)
                return "Item not found in inventory: " + itemName;

            // Find a slot that can hold this item
            EquipmentSlot slot = EquipmentSlot.GetBestEquipmentSlotForItem(hero.EquipmentSlots, item);
            if (slot == null)
                return "No compatible equipment slot available for item: " + itemName;

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            string itemName = command.GetString("item_name");

            Hero hero = FindHeroByName(heroName);
            InventoryItem item = FindItemInInventories(itemName);
            EquipmentSlot slot = EquipmentSlot.GetBestEquipmentSlotForItem(hero.EquipmentSlots, item);

            // EquipItem(item, removeFromInventory, netSync, skipRequestToServer, checkItemInventory)
            slot.EquipItem(item, true, true, false, true);

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["item_name"] = itemName;
            metadata["slot_category"] = slot.CategoryParameters != null
                ? slot.CategoryParameters.CategoryName.ToString() : "Unknown";

            return ActionResult.Ok(metadata);
        }

        private InventoryItem FindItemInInventories(string itemName)
        {
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null || dungeon.Inventories == null)
                return null;

            for (int inv = 0; inv < dungeon.Inventories.Length; inv++)
            {
                Inventory inventory = dungeon.Inventories[inv];
                if (inventory == null || inventory.Items == null)
                    continue;

                bool isShared = (inventory.Name == Inventory.SharedInventoryName);
                bool isBackpack = (inventory.Name == Inventory.BackpackInventoryName);
                if (!isShared && !isBackpack)
                    continue;

                for (int i = 0; i < inventory.Items.Count; i++)
                {
                    InventoryItem item = inventory.Items[i];
                    if (item == null || item.ItemConfig == null)
                        continue;

                    if (item.ItemConfig.Name.ToString() == itemName)
                        return item;
                }
            }
            return null;
        }

        private Hero FindHeroByName(string name)
        {
            List<Hero> heroes = Hero.LocalPlayerActiveRecruitedHeroes;
            if (heroes == null)
                return null;

            for (int i = 0; i < heroes.Count; i++)
            {
                Hero hero = heroes[i];
                if (hero == null)
                    continue;

                string heroName = hero.LocalizedName;
                if (string.IsNullOrEmpty(heroName) && hero.Config != null)
                    heroName = hero.Config.Name.ToString();

                if (heroName == name)
                    return hero;
            }
            return null;
        }
    }
}
