
#!/bin/bash
# save raw env of the running container
raw_path="$PATH"
raw_ld_path="$LD_LIBRARY_PATH"
raw_py_path="$PYTHONPATH"

# import env from parent
export $(echo $PARENT_ENV|tr -s '@@' '\n' |xargs)

# source custom ENV
. ./path.sh || echo ''
# patch env by the raw env
export PATH=$PATH:$raw_path
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$raw_ld_path
export PYTHONPATH=$PYTHONPATH:$raw_py_path

# create log path
log_path=""
if [ ! -z $LOG_FILE ]; then
    mkdir -p "${LOG_FILE%/*}"
    if [ -z $SLURM_ARRAY_TASK_ID ]; then
        log_path="${LOG_FILE/JOB/$((RANK+1))}"
    else
        log_path="${LOG_FILE/JOB/${SLURM_ARRAY_TASK_ID}_$((RANK+1))}"
    fi
fi

# print env && cmd to logfile
echo "################### env ###################" > $log_path
env | sed 's/^/#/g' >> $log_path
echo "################### info ###################" >> $log_path
now=`TZ='Asia/Shanghai' date -d now +'%Y-%m-%d %H:%M:%S'`
echo "data now: $now" >> $log_path
cat /etc/raw_hostname | xargs echo "run on node:" >> $log_path
echo -e "###########################################\n" >> $log_path
# run the task command
(LAYER1_ZERO_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/source/dfd36d3 LAYER1_TRAINING_ENV=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/envs/training LAYER1_ZERO_OUTPUT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue017-zero-update-r1 timeout 1800 bash /hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/source/dfd36d3/scripts/remote/run_layer1_zero_update.sh && LAYER1_COMPARISON_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/source/dfd36d3 LAYER1_COMPARISON_OUTPUT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue017-runtime-regression-r1 LAYER1_MODEL_ENV=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/envs/training LAYER1_WORD_MANIFEST=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-archive/runs/interclarify-issue001-word-20261019/data/word-capture-r2/word_manifest.json timeout 600 bash /hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/source/dfd36d3/scripts/remote/run_layer1_runtime_comparison.sh) >> $log_path 2>&1
