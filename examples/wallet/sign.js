// Expects:
// seq: big integer or number
// to: address, in the form 0x46d241f4....
// value: big integer or number
// data: hex data
function sign(seq, to, value, data, signingAddr) {
    var seqHex = web3.toHex(seq).substr(2);
    while (seqHex.length < 64)
        seqHex = "0" + seqHex;
    var valueHex = web3.toHex(value).substr(2);
    while (valueHex.length < 64)
        valueHex = "0" + valueHex;
    var concatData = "0x" + seqHex + "000000000000000000000000" + to.substr(2) + valueHex + data.substr(2);
    var hash = web3.sha3(concatData, {encoding: 'hex'});
    return web3.eth.sign(signingAddr, hash);
}
