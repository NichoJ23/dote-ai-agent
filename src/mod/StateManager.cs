using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent
{
    /// <summary>
    /// Orchestrates all state hooks and produces a unified GameStatePayload.
    /// </summary>
    public class StateManager
    {
        private DungeonHook dungeonHook;
        private ResourceHook resourceHook;
        private HeroHook heroHook;
        private MobHook mobHook;
        private MerchantHook merchantHook;
        private RecruitHook recruitHook;
        private ItemHook itemHook;

        private bool isBound;

        public bool IsBound { get { return isBound; } }

        public StateManager()
        {
            dungeonHook = new DungeonHook();
            resourceHook = new ResourceHook();
            heroHook = new HeroHook(dungeonHook);
            mobHook = new MobHook(dungeonHook);
            merchantHook = new MerchantHook(dungeonHook);
            recruitHook = new RecruitHook(dungeonHook);
            itemHook = new ItemHook(dungeonHook);
        }

        /// <summary>
        /// Attempts to bind all hooks to game objects. Returns true when all core hooks are bound.
        /// </summary>
        public bool TryBind()
        {
            if (isBound)
                return true;

            bool dungeonBound = dungeonHook.TryBind();
            if (!dungeonBound)
                return false;

            resourceHook.TryBind();
            heroHook.TryBind();
            mobHook.TryBind();
            merchantHook.TryBind();
            recruitHook.TryBind();
            itemHook.TryBind();

            isBound = dungeonHook.IsBound;
            return isBound;
        }

        /// <summary>
        /// Extracts a complete game state snapshot from all hooks.
        /// Returns null if the dungeon hook isn't bound or state isn't available.
        /// </summary>
        public GameStatePayload ExtractFullState()
        {
            if (!isBound)
                return null;

            // Dungeon state (rooms, doors)
            DungeonStateData dungeonState = dungeonHook.ExtractState() as DungeonStateData;
            if (dungeonState == null)
                return null;

            // Resources
            ResourceStateData resources = resourceHook.ExtractState() as ResourceStateData;

            // Heroes
            List<HeroStateData> heroes = heroHook.ExtractState() as List<HeroStateData>;

            // Mobs
            List<MobStateData> mobs = mobHook.ExtractState() as List<MobStateData>;

            // Merchants
            List<MerchantStateData> merchants = merchantHook.ExtractState() as List<MerchantStateData>;

            // Recruitable heroes
            List<RecruitableHeroData> recruits = recruitHook.ExtractState() as List<RecruitableHeroData>;

            // Dropped items
            List<DroppedItemData> items = itemHook.ExtractState() as List<DroppedItemData>;

            // Assemble payload
            var payload = new GameStatePayload();
            payload.Turn = dungeonState.Turn;
            payload.Floor = dungeonState.Floor;
            payload.GamePhase = dungeonState.GamePhase;
            payload.CrystalState = dungeonState.CrystalState;
            payload.ExitRoomIndex = dungeonState.ExitRoomIndex;
            payload.StartRoomIndex = dungeonState.StartRoomIndex;
            payload.TimeScale = UnityEngine.Time.timeScale;

            // Check if level is over (game over or floor escaped)
            Dungeon dungeonForLevelOver = SingletonManager.Get<Dungeon>(false);
            payload.IsLevelOver = (dungeonForLevelOver != null && dungeonForLevelOver.IsLevelOver);
            payload.Resources = resources;
            payload.Rooms = dungeonState.Rooms;
            payload.ClosedDoors = dungeonState.ClosedDoors;
            payload.Heroes = heroes ?? new List<HeroStateData>();
            payload.Mobs = mobs ?? new List<MobStateData>();
            payload.Merchants = merchants ?? new List<MerchantStateData>();
            payload.RecruitableHeroes = recruits ?? new List<RecruitableHeroData>();
            payload.DroppedItems = items ?? new List<DroppedItemData>();
            ExtractInventories(payload);
            ExtractResearchableBlueprints(payload);
            ExtractBuildableBlueprints(payload);

            return payload;
        }

        /// <summary>
        /// Provides access to the DungeonHook for room index lookups.
        /// </summary>
        public DungeonHook GetDungeonHook()
        {
            return dungeonHook;
        }

        private void ExtractInventories(GameStatePayload payload)
        {
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            payload.BackpackItems = new List<BackpackItemData>();
            payload.SharedInventoryItems = new List<BackpackItemData>();

            if (dungeon == null || dungeon.Inventories == null)
                return;

            for (int inv = 0; inv < dungeon.Inventories.Length; inv++)
            {
                Inventory inventory = dungeon.Inventories[inv];
                if (inventory == null || inventory.Items == null)
                    continue;

                bool isBackpack = (inventory.Name == Inventory.BackpackInventoryName);
                bool isShared = (inventory.Name == Inventory.SharedInventoryName);

                for (int i = 0; i < inventory.Items.Count; i++)
                {
                    InventoryItem item = inventory.Items[i];
                    if (item == null)
                        continue;

                    var data = new BackpackItemData();
                    data.Name = (item.ItemConfig != null) ? item.ItemConfig.Name.ToString() : "Unknown";
                    data.Rarity = (item.RarityCfg != null) ? item.RarityCfg.Name.ToString() : "Common";
                    data.Category = (item.ItemConfig != null && item.ItemConfig.CategoryParameters != null)
                        ? item.ItemConfig.CategoryParameters.CategoryName.ToString()
                        : "Unknown";

                    if (isBackpack)
                        payload.BackpackItems.Add(data);
                    else if (isShared)
                        payload.SharedInventoryItems.Add(data);
                }
            }
        }

        private void ExtractResearchableBlueprints(GameStatePayload payload)
        {
            payload.ResearchableBlueprints = new List<ResearchBlueprintData>();

            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return;

            BluePrintConfig[] bps = dungeon.GetResearchableBPs();
            if (bps == null)
                return;

            for (int i = 0; i < bps.Length; i++)
            {
                if (bps[i] != null)
                {
                    var data = new ResearchBlueprintData();
                    data.Name = bps[i].Name.ToString();
                    data.ScienceCost = bps[i].ResearchScienceCost;
                    payload.ResearchableBlueprints.Add(data);
                }
            }
        }

        private void ExtractBuildableBlueprints(GameStatePayload payload)
        {
            payload.BuildableBlueprints = new List<BuildableBlueprintData>();

            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return;

            // Iterate all module categories to get unlocked blueprints
            ModuleCategory[] categories = new ModuleCategory[]
            {
                ModuleCategory.MajorModule,
                ModuleCategory.MinorModule_Support,
                ModuleCategory.MinorModule_Offense,
                ModuleCategory.MinorModule_Debuff,
            };

            for (int c = 0; c < categories.Length; c++)
            {
                List<BluePrintConfig> unlocked = dungeon.GetCategoryUnlockedBluePrints(categories[c]);
                if (unlocked == null)
                    continue;

                for (int i = 0; i < unlocked.Count; i++)
                {
                    BluePrintConfig bp = unlocked[i];
                    if (bp == null)
                        continue;

                    var data = new BuildableBlueprintData();
                    data.Name = bp.Name.ToString();
                    data.ModuleName = bp.ModuleName ?? "";
                    data.Category = categories[c].ToString();
                    data.Level = bp.ModuleLevel;

                    // Get actual industry cost (includes increment based on existing modules)
                    ModuleConfig modConfig = bp.GetModuleConfig();
                    if (modConfig != null)
                    {
                        data.IndustryCost = modConfig.GetIndustryCost();
                    }
                    else
                    {
                        data.IndustryCost = 0f;
                    }

                    payload.BuildableBlueprints.Add(data);
                }
            }
        }
    }
}
