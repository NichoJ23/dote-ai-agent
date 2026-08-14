using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts merchant NPCs and their inventories from opened rooms.
    /// Now includes weapon type/attack type for weapon items in inventory.
    /// </summary>
    public class MerchantHook : IStateHook
    {
        private DungeonHook dungeonHook;
        private Dungeon dungeon;

        public string HookId { get { return "merchants"; } }
        public bool IsBound { get { return dungeonHook != null && dungeonHook.IsBound; } }

        public MerchantHook(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public bool TryBind()
        {
            dungeon = SingletonManager.Get<Dungeon>(false);
            return dungeonHook != null && dungeonHook.IsBound && dungeon != null;
        }

        public object ExtractState()
        {
            if (dungeon == null)
                dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return new List<MerchantStateData>();

            var result = new List<MerchantStateData>();
            List<Room> rooms = dungeon.OpenedRooms;
            if (rooms == null)
                return result;

            for (int r = 0; r < rooms.Count; r++)
            {
                Room room = rooms[r];
                if (room == null || room.NPCs == null || room.NPCs.Count == 0)
                    continue;

                for (int n = 0; n < room.NPCs.Count; n++)
                {
                    NPCMerchant merchant = room.NPCs[n] as NPCMerchant;
                    if (merchant == null)
                        continue;

                    var data = new MerchantStateData();
                    data.RoomIndex = dungeonHook.GetRoomIndex(room);
                    data.CurrencyType = merchant.CurrencyCfg != null
                        ? merchant.CurrencyCfg.Currency.ToString()
                        : "Dust";

                    data.Items = new List<MerchantItemData>();
                    if (merchant.CurrentInventory != null && merchant.CurrentInventory.Items != null)
                    {
                        for (int i = 0; i < merchant.CurrentInventory.Items.Count; i++)
                        {
                            InventoryItem item = merchant.CurrentInventory.Items[i];
                            if (item == null)
                                continue;

                            var itemData = new MerchantItemData();
                            itemData.Name = (item.ItemConfig != null)
                                ? item.ItemConfig.Name.ToString()
                                : "Unknown";
                            itemData.Rarity = (item.RarityCfg != null)
                                ? item.RarityCfg.Name.ToString()
                                : "Common";
                            itemData.Cost = item.GetCost(merchant);

                            // Extract category and weapon class info
                            if (item.ItemConfig != null)
                            {
                                ItemHeroConfig cfg = item.ItemConfig;
                                if (cfg.CategoryParameters != null)
                                {
                                    itemData.Category = cfg.CategoryParameters.CategoryName != null
                                        ? cfg.CategoryParameters.CategoryName.ToString()
                                        : null;
                                    if (cfg.CategoryParameters.TypeName != null)
                                    {
                                        itemData.WeaponType = cfg.CategoryParameters.TypeName.ToString();
                                    }
                                }
                                if (cfg.AttackTypeConfigName != null)
                                {
                                    itemData.AttackType = cfg.AttackTypeConfigName.ToString();
                                }
                            }

                            data.Items.Add(itemData);
                        }
                    }

                    result.Add(data);
                }
            }

            return result;
        }
    }
}
