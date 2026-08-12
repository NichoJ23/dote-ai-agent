using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles UNEQUIP_ITEM command: removes an equipped item from a hero's slot.
    /// The item returns to the best available inventory (shared or backpack).
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to unequip from
    ///   slot_index (int, required) - Index of the equipment slot to unequip (0-based)
    /// </summary>
    public class UnequipItemHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "UNEQUIP_ITEM"; } }

        public UnequipItemHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            if (string.IsNullOrEmpty(heroName))
                return "Missing required parameter: hero_name";

            int slotIndex = command.GetInt("slot_index", -1);
            if (slotIndex < 0)
                return "Missing or invalid parameter: slot_index";

            Hero hero = FindHeroByName(heroName);
            if (hero == null)
                return "Hero not found: " + heroName;

            EquipmentSlot[] slots = hero.EquipmentSlots;
            if (slots == null || slotIndex >= slots.Length)
                return "Invalid slot_index: " + slotIndex + " (hero has " + (slots != null ? slots.Length : 0) + " slots)";

            EquipmentSlot slot = slots[slotIndex];
            if (slot == null)
                return "Slot " + slotIndex + " is null";

            if (slot.EquippedItem == null)
                return "No item equipped in slot " + slotIndex;

            if (slot.EquippedItem.ItemConfig != null && slot.EquippedItem.ItemConfig.CannotBeUnequipped)
                return "Item in slot " + slotIndex + " cannot be unequipped";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            int slotIndex = command.GetInt("slot_index", -1);

            Hero hero = FindHeroByName(heroName);
            EquipmentSlot slot = hero.EquipmentSlots[slotIndex];

            string itemName = slot.EquippedItem.ItemConfig != null
                ? slot.EquippedItem.ItemConfig.Name.ToString() : "Unknown";

            // UnequipItem(netSync, checkConfig)
            slot.UnequipItem(true, true);

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["slot_index"] = slotIndex;
            metadata["item_name"] = itemName;

            return ActionResult.Ok(metadata);
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
