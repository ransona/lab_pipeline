import datetime
import sys


def run_preprocess_bonvision(userID, expID):
    exp_date = expID[0:10]
    bonvision_v2_cutoff = datetime.datetime.strptime('2025-01-24', '%Y-%m-%d')
    if datetime.datetime.strptime(exp_date, '%Y-%m-%d') > bonvision_v2_cutoff:
        from preprocess_pipeline.behavior import preprocess_bv2
        preprocess_bv2.run_preprocess_bv2(userID, expID)
    else:
        from preprocess_pipeline.behavior import preprocess_bv
        preprocess_bv.run_preprocess_bv(userID, expID)


def main():
    if len(sys.argv) == 3:
        run_preprocess_bonvision(sys.argv[1], sys.argv[2])
        return

    userID = 'adamranson'
    expID = '2025-04-10_26_TEST'
    run_preprocess_bonvision(userID, expID)


if __name__ == "__main__":
    main()
