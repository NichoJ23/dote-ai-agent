using System.Collections.Generic;
using DotEAgent.Models;
using UnityEngine;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts dropped items on the floor: dust piles from killed mobs and equipment items.
    /// </summary>
    public class ItemHook : IStateHook
    {
        private DungeonHook dungeonHook;

        public string HookId { get { return "items"; } }
        public bool IsBound { get { return dungeonHook != null && dungeonHook.IsBound; } }

        public ItemHook(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public bool TryBind()
        {
            return dungeonHook != null && dungeonHook.IsBound;
        }

        public object ExtractState()
        {
            var result = new List<DroppedItemData>();

            // Find dust piles dropped by mobs
            MobDustLoot[] dustLoots = Object.FindObjectsOfType<MobDustLoot>();
            if (dustLoots != null)
            {
                for (int i = 0; i < dustLoots.Length; i++)
                {
                    MobDustLoot loot = dustLoots[i];
                    if (loot == null || loot.ParentRoom == null)
                        continue;

                    var data = new DroppedItemData();
                    data.Type = "Dust";
                    data.Name = null;
                    data.RoomIndex = dungeonHook.GetRoomIndex(loot.ParentRoom);
                    data.DustAmount = loot.DustAmount;
                    result.Add(data);
                }
            }

            // Find equipment/item pickups on the ground
            Item[] items = Object.FindObjectsOfType<Item>();
            if (items != null)
            {
                for (int i = 0; i < items.Length; i++)
                {
                    Item item = items[i];
                    if (item == null)
                        continue;
                    if (item.IsAcquired)
                        continue;
                    if (!item.CanBeGathered)
                        continue;

                    var data = new DroppedItemData();
                    data.Type = item.Type.ToString();
                    data.Name = (item.ItemName != null) ? item.ItemName.ToString() : "Unknown";

                    if (item.RoomElement != null && item.RoomElement.ParentRoom != null)
                    {
                        data.RoomIndex = dungeonHook.GetRoomIndex(item.RoomElement.ParentRoom);
                    }
                    else
                    {
                        data.RoomIndex = -1;
                    }

                    result.Add(data);
                }
            }

            return result;
        }
    }
}
