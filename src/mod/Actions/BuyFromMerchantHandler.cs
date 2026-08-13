using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles BUY_FROM_MERCHANT command: purchases an item from a merchant.
    /// Hero must be in the merchant's room.
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero buying (must be in merchant's room)
    ///   merchant_room_index (int, required) - Room where the merchant is
    ///   item_name (string, required) - Name of the item to buy
    /// </summary>
    public class BuyFromMerchantHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "BUY_FROM_MERCHANT"; } }

        public BuyFromMerchantHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            if (string.IsNullOrEmpty(heroName))
                return "Missing required parameter: hero_name";

            int merchantRoomIndex = command.GetInt("merchant_room_index", -1);
            if (merchantRoomIndex < 0)
                return "Missing or invalid parameter: merchant_room_index";

            string itemName = command.GetString("item_name");
            if (string.IsNullOrEmpty(itemName))
                return "Missing required parameter: item_name";

            // Find hero
            Hero hero = FindHeroByName(heroName);
            if (hero == null)
                return "Hero not found: " + heroName;

            if (!hero.IsUsable)
                return "Hero is not usable: " + heroName;

            // Validate room
            Room merchantRoom = dungeonHook.GetRoomByOpeningIndex(merchantRoomIndex);
            if (merchantRoom == null)
                return "Invalid merchant_room_index: " + merchantRoomIndex + " (room not found)";

            // Validate hero is in merchant's room
            Room heroRoom = hero.RoomElement.ParentRoom;
            if (heroRoom != merchantRoom)
            {
                int actualRoom = dungeonHook.GetRoomIndex(heroRoom);
                return "Hero " + heroName + " is in room " + actualRoom
                    + ", not in merchant's room " + merchantRoomIndex;
            }

            // Find merchant in room
            NPCMerchant merchant = FindMerchantInRoom(merchantRoom);
            if (merchant == null)
                return "No merchant found in room " + merchantRoomIndex;

            // Find item in merchant's inventory
            InventoryItem item = FindItemByName(merchant, itemName);
            if (item == null)
                return "Item not found in merchant inventory: " + itemName;

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            int merchantRoomIndex = command.GetInt("merchant_room_index", -1);
            string itemName = command.GetString("item_name");

            Room merchantRoom = dungeonHook.GetRoomByOpeningIndex(merchantRoomIndex);

            NPCMerchant merchant = FindMerchantInRoom(merchantRoom);
            InventoryItem item = FindItemByName(merchant, itemName);

            // Use the same RPC path the UI uses:
            // merchant.NetSyncElement.SendRPCToServer(RequestBuyItemFromMerchantPanel, category, id, buyerID)
            GameNetworkManager netManager = SingletonManager.Get<GameNetworkManager>(true);
            ulong buyerID = netManager.GetLocalPlayerID();

            merchant.NetSyncElement.SendRPCToServer(
                UniqueIDRPC.NPCMerchant_RequestBuyItemFromMerchantPanel,
                new object[] { item.UniqueIDCategory, item.UniqueID, buyerID }
            );

            var metadata = new Dictionary<string, object>();
            metadata["item_name"] = itemName;
            metadata["merchant_room_index"] = merchantRoomIndex;

            return ActionResult.Ok(metadata);
        }

        private NPCMerchant FindMerchantInRoom(Room room)
        {
            if (room.NPCs == null)
                return null;

            for (int i = 0; i < room.NPCs.Count; i++)
            {
                NPCMerchant merchant = room.NPCs[i] as NPCMerchant;
                if (merchant != null)
                    return merchant;
            }
            return null;
        }

        private InventoryItem FindItemByName(NPCMerchant merchant, string itemName)
        {
            if (merchant.CurrentInventory == null || merchant.CurrentInventory.Items == null)
                return null;

            for (int i = 0; i < merchant.CurrentInventory.Items.Count; i++)
            {
                InventoryItem item = merchant.CurrentInventory.Items[i];
                if (item == null || item.ItemConfig == null)
                    continue;

                if (item.ItemConfig.Name.ToString() == itemName)
                    return item;
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
