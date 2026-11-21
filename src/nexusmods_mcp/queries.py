"""Public fields from the Nexus GraphQL v2 schema. REST v3 provides gallery images."""

GAME = """
    id domainName name approvedAt artworkSchema collectionCount copyrightedName
    downloadCount forumUrl genre imageCount mediaCount modCount supporterImageCount
    supportsVortex trendingPeriodDays uniqueDownloadCount videoCount
"""
MOD_CARD = """
    uid modId gameId name author summary updatedAt version pictureUrl
    downloads endorsements game { id domainName name }
"""
MOD = (
    MOD_CARD
    + """
    id adultContent category createdAt description directDownloadEnabled fileSize
    isBlockedFromEarningDp legacyModRequirementsEnabled status supportsVortex
    thumbnailBlurredUrl thumbnailLargeBlurredUrl thumbnailLargeUrl thumbnailUrl
    modCategory { id categoryId gameId name date }
    tags { id name parentId blockable global retired retiredAt searchable }
    uploader { memberId name avatar about joined recognizedAuthor modCount }
    mirrors { id gameId modId uri name count totalDownloads }
"""
)
FILE = """
    id uid fileId modId modUid category categoryId changelogText count date description
    detectedFileExtension groupId manager name primary reportLink requirementsAlert
    scanned scannedV2 size sizeInBytes sqid totalDownloads uCount uniqueDownloads uri version
    owner { memberId name avatar } game { id name domainName }
"""
REQUIREMENT = "externalRequirement gameId id modId modName notes url"
GAMES = (
    """query Games($filter: GamesSearchFilter, $sort: [GamesSearchSort!], $offset: Int!, $count: Int!) {
    games(filter: $filter, sort: $sort, offset: $offset, count: $count) {
        totalCount nodesCount nodes { """
    + GAME
    + """ }
    }
}"""
)
MODS = (
    """query Mods($filter: ModsFilter, $sort: [ModsSort!], $offset: Int!, $count: Int!) {
    mods(filter: $filter, sort: $sort, offset: $offset, count: $count) {
        totalCount nodesCount nodes { """
    + MOD_CARD
    + """ }
    }
}"""
)
GAME_ID = (
    "query GameId($domain: String!) { game(domainName: $domain) { id domainName } }"
)
MOD_DETAILS = (
    "query ModDetails($gid: ID!, $mid: ID!) { mod(gameId: $gid, modId: $mid) { "
    + MOD
    + " } }"
)
FILES = (
    "query Files($gid: ID!, $mid: ID!) { modFiles(gameId: $gid, modId: $mid) { "
    + FILE
    + " } }"
)
REQUIREMENTS = """query Requirements($gid: ID!, $mid: ID!, $offset: Int!, $reverseOffset: Int!, $count: Int!, $skipDisabled: Boolean!) {
    mod(gameId: $gid, modId: $mid) {
        legacyModRequirementsEnabled
        modRequirements(skipDisabledRequirements: $skipDisabled) {
            dlcRequirements { notes gameExpansion { id gameId name } }
            nexusRequirements(offset: $offset, count: $count) { totalCount nodesCount nodes { FIELDS } }
            modsRequiringThisMod(offset: $reverseOffset, count: $count) { totalCount nodesCount nodes { FIELDS } }
        }
    }
}""".replace("FIELDS", REQUIREMENT)
