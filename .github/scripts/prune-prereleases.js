module.exports = async ({github, context}) => {
    console.log('Pruning old prereleases')
  
    const { data: releases } = await github.rest.repos.listReleases({
      owner: context.repo.owner,
      repo: context.repo.repo
    })
  
    let prereleases = releases.filter(
      (release) => release.tag_name.includes('pre-release')
    )
  
    for (const prerelease of prereleases) {
      console.log(`Deleting prerelase: ${prerelease.tag_name}`)
      await github.rest.repos.deleteRelease({
        owner: context.repo.owner,
        repo: context.repo.repo,
        release_id: prerelease.id
      })
    }
  
    console.log('Done.')
  }